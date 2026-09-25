"""Explicit human reviewer decisions and operator audit events for durable runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .durable import (
    AUDIT_SCHEMA,
    AuditEvent,
    AuditEventType,
    DurableEvidenceRef,
    FileAuditStore,
    FileEvidenceStore,
    FileStateStore,
    HumanDecisionResult,
    HumanDecisionStatus,
)
from .escalation import ReviewerAction, ReviewerDecision
from .models import RunStatus, new_id, utc_now
from .recovery import verify_run_consistency
from .state_machine import FoundationStateMachine, InvalidStateTransition


def apply_reviewer_decision(
    artifacts_root: Path,
    run_id: str,
    *,
    action: str,
    reviewer_id: str = "",
    comment: str = "",
    escalation_id: str | None = None,
) -> HumanDecisionResult:
    """Record an explicit human decision for an AWAITING_HUMAN run.

    APPROVE / REJECT transition the durable workflow. REQUEST_CHANGES / DEFER
    record the decision and remain AWAITING_HUMAN.

    Never applies a patch to the primary workspace.
    """

    store = FileStateStore(artifacts_root)
    audit = FileAuditStore(artifacts_root)
    evidence = FileEvidenceStore(artifacts_root)

    try:
        state = store.load_run(run_id)
    except Exception as exc:  # noqa: BLE001
        return HumanDecisionResult(
            HumanDecisionStatus.BLOCKED,
            run_id,
            "",
            "",
            action,
            f"cannot load run: {exc}",
        )

    before = state.workflow_status
    report = verify_run_consistency(artifacts_root=artifacts_root, run_id=run_id, state=state)
    if not report.valid:
        return HumanDecisionResult(
            HumanDecisionStatus.INCONSISTENT,
            run_id,
            before,
            before,
            action,
            "; ".join(i.message for i in report.issues),
            state.last_event_sequence,
        )

    if before != RunStatus.AWAITING_HUMAN.value:
        return HumanDecisionResult(
            HumanDecisionStatus.BLOCKED,
            run_id,
            before,
            before,
            action,
            f"reviewer decisions require AWAITING_HUMAN, found {before}",
            state.last_event_sequence,
        )

    try:
        reviewed = ReviewerAction(action.strip().upper())
    except ValueError:
        return HumanDecisionResult(
            HumanDecisionStatus.BLOCKED,
            run_id,
            before,
            before,
            action,
            f"invalid reviewer action '{action}'; "
            f"use {[a.value for a in ReviewerAction]}",
            state.last_event_sequence,
        )

    # Resolve escalation id from package when not provided
    resolved_esc = escalation_id
    esc_payload: dict[str, Any] = {}
    root = Path(artifacts_root) / "runs" / run_id
    summary_path = root / "escalation" / "summary.json"
    if summary_path.is_file():
        try:
            esc_payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return HumanDecisionResult(
                HumanDecisionStatus.INCONSISTENT,
                run_id,
                before,
                before,
                action,
                f"escalation summary unreadable: {exc}",
                state.last_event_sequence,
            )
        if not resolved_esc:
            resolved_esc = str(esc_payload.get("escalation_id") or "")
    if not resolved_esc:
        return HumanDecisionResult(
            HumanDecisionStatus.BLOCKED,
            run_id,
            before,
            before,
            action,
            "escalation_id required (or escalation/summary.json must define it)",
            state.last_event_sequence,
        )
    if esc_payload and str(esc_payload.get("escalation_id") or "") not in {"", resolved_esc}:
        return HumanDecisionResult(
            HumanDecisionStatus.BLOCKED,
            run_id,
            before,
            before,
            action,
            "escalation_id does not match escalation package",
            state.last_event_sequence,
        )

    decision = ReviewerDecision(
        escalation_id=resolved_esc,
        action=reviewed,
        reviewer_id=reviewer_id,
        comment=comment,
    )
    decision_ref = evidence.write_json(
        run_id,
        "reviewer",
        decision.to_dict(),
        name="decision.json",
    )

    # Map action → next workflow status (APPROVE still does not mutate primary tree)
    transitions: dict[ReviewerAction, tuple[RunStatus, AuditEventType | None, HumanDecisionStatus, str]] = {
        ReviewerAction.APPROVE: (
            RunStatus.APPROVED,
            AuditEventType.HUMAN_APPROVED,
            HumanDecisionStatus.APPLIED,
            "Human APPROVE recorded; workflow APPROVED. "
            "Primary workspace was not mutated.",
        ),
        ReviewerAction.REJECT: (
            RunStatus.REJECTED,
            AuditEventType.HUMAN_REJECTED,
            HumanDecisionStatus.APPLIED,
            "Human REJECT recorded; workflow REJECTED.",
        ),
        ReviewerAction.REQUEST_CHANGES: (
            RunStatus.AWAITING_HUMAN,
            None,
            HumanDecisionStatus.RECORDED,
            "Human REQUEST_CHANGES recorded; still AWAITING_HUMAN "
            "(no workflow terminal transition).",
        ),
        ReviewerAction.DEFER: (
            RunStatus.AWAITING_HUMAN,
            None,
            HumanDecisionStatus.RECORDED,
            "Human DEFER recorded; still AWAITING_HUMAN "
            "(no workflow terminal transition).",
        ),
    }
    next_status, terminal_event, result_status, message = transitions[reviewed]

    if next_status is not RunStatus.AWAITING_HUMAN:
        try:
            sm = FoundationStateMachine(RunStatus.AWAITING_HUMAN)
            sm.transition(next_status, f"human:{reviewed.value}")
        except InvalidStateTransition as exc:
            return HumanDecisionResult(
                HumanDecisionStatus.BLOCKED,
                run_id,
                before,
                before,
                action,
                str(exc),
                state.last_event_sequence,
            )

    seq = audit.latest_sequence(run_id) + 1
    recorded = AuditEvent(
        schema_version=AUDIT_SCHEMA,
        event_id=new_id("evt"),
        run_id=run_id,
        sequence=seq,
        timestamp=utc_now(),
        event_type=AuditEventType.HUMAN_DECISION_RECORDED.value,
        actor=reviewer_id or "human",
        component="human_decision",
        state_before=before,
        state_after=next_status.value,
        evidence_refs=(decision_ref,),
        metadata={
            "action": reviewed.value,
            "escalation_id": resolved_esc,
            "primary_workspace_mutated": False,
            "comment": comment[:500] if comment else "",
        },
    )
    audit.append(recorded)
    state.last_event_sequence = seq
    state.reviewer_decision_ref = decision_ref.ref
    state.updated_at = utc_now()
    state.workflow_status = next_status.value
    if reviewed is ReviewerAction.APPROVE:
        state.stop_reason = "human_approve"
    elif reviewed is ReviewerAction.REJECT:
        state.stop_reason = "human_reject"
    store.save_run(state)

    if terminal_event is not None:
        seq2 = audit.latest_sequence(run_id) + 1
        follow = AuditEvent(
            schema_version=AUDIT_SCHEMA,
            event_id=new_id("evt"),
            run_id=run_id,
            sequence=seq2,
            timestamp=utc_now(),
            event_type=terminal_event.value,
            actor=reviewer_id or "human",
            component="human_decision",
            state_before=before,
            state_after=next_status.value,
            evidence_refs=(decision_ref,),
            metadata={"action": reviewed.value, "primary_workspace_mutated": False},
        )
        audit.append(follow)
        state.last_event_sequence = seq2
        state.updated_at = utc_now()
        store.save_run(state)
        seq = seq2

    return HumanDecisionResult(
        result_status,
        run_id,
        before,
        next_status.value,
        reviewed.value,
        message,
        seq,
        primary_workspace_mutated=False,
    )


def append_operator_event(
    artifacts_root: Path,
    run_id: str,
    event_type: AuditEventType,
    *,
    actor: str,
    component: str,
    metadata: dict[str, Any] | None = None,
    evidence_refs: tuple[DurableEvidenceRef, ...] = (),
) -> int:
    """Append an operator-initiated audit event without changing workflow status.

    Used for side effects that happen after a terminal workflow decision
    (for example applying an APPROVED patch to a target repository).
    """

    store = FileStateStore(artifacts_root)
    audit = FileAuditStore(artifacts_root)
    state = store.load_run(run_id)
    seq = audit.latest_sequence(run_id) + 1
    audit.append(
        AuditEvent(
            schema_version=AUDIT_SCHEMA,
            event_id=new_id("evt"),
            run_id=run_id,
            sequence=seq,
            timestamp=utc_now(),
            event_type=event_type.value,
            actor=actor or "operator",
            component=component,
            state_before=state.workflow_status,
            state_after=state.workflow_status,
            evidence_refs=evidence_refs,
            metadata=dict(metadata or {}),
        )
    )
    state.last_event_sequence = seq
    store.save_run(state)
    return seq

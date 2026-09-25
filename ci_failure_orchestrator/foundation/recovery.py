"""Phase 10 — recovery assessment, consistency verification, inspection and replay."""

from __future__ import annotations

from pathlib import Path

from .durable import (
    AUDIT_SCHEMA,
    AuditEvent,
    AuditEventType,
    ConsistencyIssue,
    ConsistencyReport,
    DurableRunState,
    FileAuditStore,
    FileStateStore,
    PersistenceError,
    RecoveryDecision,
    RecoveryStatus,
    RunInspection,
)
from .models import RunStatus, new_id, utc_now

_TERMINAL = frozenset(
    {
        RunStatus.APPROVED.value,
        RunStatus.REJECTED.value,
        RunStatus.AWAITING_HUMAN.value,
        RunStatus.ESCALATION_ERROR.value,
        RunStatus.FAILED.value,
        RunStatus.SUCCEEDED.value,
        "PERSISTENCE_ERROR",
    }
)

_RESUMABLE = frozenset(
    {
        RunStatus.RECEIVED.value,
        RunStatus.CONTEXT_READY.value,
        RunStatus.CLASSIFIED.value,
        RunStatus.PLANNED.value,
        RunStatus.PROPOSAL_READY.value,
        RunStatus.EVALUATED.value,
        RunStatus.RETRY_DECISION.value,
        RunStatus.RETRYING.value,
        RunStatus.POLICY_REVIEW.value,
    }
)

_UNSAFE = frozenset(
    {
        RunStatus.EXECUTING.value,
        RunStatus.SANDBOX_RUNNING.value,
        RunStatus.EVALUATING.value,
        RunStatus.ESCALATION_BUILDING.value,
        RunStatus.ESCALATED.value,
    }
)


def assess_recovery(state: DurableRunState) -> RecoveryDecision:
    status = state.workflow_status
    if status in _TERMINAL:
        extra = ""
        if status == RunStatus.AWAITING_HUMAN.value:
            extra = (
                " Use foundation-decide with an explicit reviewer action to "
                "leave AWAITING_HUMAN (APPROVE still does not mutate the primary workspace)."
            )
        return RecoveryDecision(
            RecoveryStatus.TERMINAL,
            state.run_id,
            status,
            "Automated execution is complete for this workflow status." + extra,
            state.last_event_sequence,
        )
    if status in _UNSAFE:
        return RecoveryDecision(
            RecoveryStatus.REQUIRES_REVIEW,
            state.run_id,
            status,
            "Interrupted during a side-effecting or ambiguous step; do not auto-resume.",
            state.last_event_sequence,
        )
    if status in _RESUMABLE:
        return RecoveryDecision(
            RecoveryStatus.RESUMABLE,
            state.run_id,
            status,
            "Safe to resume from last durable checkpoint (no automatic side effects).",
            state.last_event_sequence,
        )
    return RecoveryDecision(
        RecoveryStatus.REQUIRES_REVIEW,
        state.run_id,
        status,
        f"Unknown workflow status '{status}' requires review.",
        state.last_event_sequence,
    )


def verify_run_consistency(
    *,
    artifacts_root: Path,
    run_id: str,
    state: DurableRunState | None = None,
    events: list[AuditEvent] | None = None,
) -> ConsistencyReport:
    root = Path(artifacts_root) / "runs" / run_id
    issues: list[ConsistencyIssue] = []
    state_store = FileStateStore(artifacts_root)
    audit_store = FileAuditStore(artifacts_root)

    try:
        state = state or state_store.load_run(run_id)
    except Exception as exc:  # noqa: BLE001
        return ConsistencyReport(
            False,
            (ConsistencyIssue("STATE_LOAD", str(exc)),),
        )

    try:
        if events is None:
            events, trailing = audit_store.read_events_tolerant(run_id)
            if trailing:
                issues.append(
                    ConsistencyIssue(
                        "TRAILING_CORRUPT_EVENT",
                        "events.jsonl has a malformed trailing record",
                    )
                )
    except PersistenceError as exc:
        issues.append(ConsistencyIssue("AUDIT_READ", str(exc)))
        events = events or []

    # Sequence continuity
    expected = 1
    for ev in events or []:
        if ev.sequence != expected:
            issues.append(
                ConsistencyIssue(
                    "SEQUENCE_GAP",
                    f"expected sequence {expected}, found {ev.sequence}",
                )
            )
            break
        expected += 1

    if state.last_event_sequence and events:
        if state.last_event_sequence != events[-1].sequence:
            issues.append(
                ConsistencyIssue(
                    "STATE_EVENT_SEQUENCE_MISMATCH",
                    f"state.last_event_sequence={state.last_event_sequence} "
                    f"!= last event sequence={events[-1].sequence}",
                )
            )

    def _check_ref(label: str, ref: str | None) -> None:
        if not ref:
            return
        path = root / ref
        if not path.is_file():
            issues.append(ConsistencyIssue("MISSING_ARTIFACT", f"{label} missing: {ref}"))

    _check_ref("failure_event", state.failure_event_ref)
    _check_ref("classification", state.classification_ref)
    _check_ref("plan", state.current_plan_ref)
    _check_ref("proposal", state.current_proposal_ref)
    _check_ref("evaluation", state.latest_evaluation_ref)
    _check_ref("policy", state.latest_policy_decision_ref)
    _check_ref("retry", state.latest_retry_decision_ref)
    _check_ref("escalation", state.escalation_ref)
    _check_ref("reviewer_decision", state.reviewer_decision_ref)

    if state.workflow_status == RunStatus.AWAITING_HUMAN.value:
        esc = root / "escalation" / "summary.json"
        if not esc.is_file() and not state.escalation_ref:
            issues.append(
                ConsistencyIssue(
                    "MISSING_ESCALATION",
                    "AWAITING_HUMAN but escalation summary artifact missing",
                )
            )

    # State vs events for evaluation
    if state.workflow_status in {
        RunStatus.EVALUATED.value,
        RunStatus.POLICY_REVIEW.value,
        RunStatus.APPROVED.value,
        RunStatus.REJECTED.value,
        RunStatus.AWAITING_HUMAN.value,
    }:
        if not any(e.event_type == AuditEventType.EVALUATION_COMPLETED.value for e in (events or [])):
            issues.append(
                ConsistencyIssue(
                    "MISSING_EVAL_EVENT",
                    f"state={state.workflow_status} but no EVALUATION_COMPLETED event",
                )
            )

    return ConsistencyReport(valid=not issues, issues=tuple(issues))


def inspect_run(artifacts_root: Path, run_id: str) -> RunInspection:
    store = FileStateStore(artifacts_root)
    audit = FileAuditStore(artifacts_root)
    state = store.load_run(run_id)
    events, _ = audit.read_events_tolerant(run_id)
    last = events[-1] if events else None
    return RunInspection(
        run_id=run_id,
        workflow_status=state.workflow_status,
        technical_status=state.technical_status,
        policy_outcome=state.policy_outcome,
        current_attempt=state.current_attempt,
        last_event=last.event_type if last else None,
        last_sequence=last.sequence if last else 0,
        created_at=state.created_at,
        updated_at=state.updated_at,
        evidence_root=str((Path(artifacts_root) / "runs" / run_id).as_posix()),
    )


def replay_events(artifacts_root: Path, run_id: str) -> list[str]:
    events, trailing = FileAuditStore(artifacts_root).read_events_tolerant(run_id)
    lines = [f"#{e.sequence} {e.event_type}" for e in events]
    if trailing:
        lines.append("#? TRAILING_CORRUPT_RECORD")
    return lines


def resume_run(artifacts_root: Path, run_id: str) -> RecoveryDecision:
    """Load durable state and decide recovery — does not re-execute tools."""

    store = FileStateStore(artifacts_root)
    audit = FileAuditStore(artifacts_root)
    state = store.load_run(run_id)
    report = verify_run_consistency(artifacts_root=artifacts_root, run_id=run_id, state=state)
    if not report.valid:
        return RecoveryDecision(
            RecoveryStatus.INCONSISTENT,
            run_id,
            state.workflow_status,
            "; ".join(i.message for i in report.issues),
            state.last_event_sequence,
        )
    decision = assess_recovery(state)
    if decision.status is RecoveryStatus.RESUMABLE:
        # Emit RUN_RESUMED marker only — no automatic continuation of side effects
        seq = audit.latest_sequence(run_id) + 1
        event = AuditEvent(
            schema_version=AUDIT_SCHEMA,
            event_id=new_id("evt"),
            run_id=run_id,
            sequence=seq,
            timestamp=utc_now(),
            event_type=AuditEventType.RUN_RESUMED.value,
            actor="orchestrator",
            component="persistence",
            state_before=state.workflow_status,
            state_after=state.workflow_status,
            metadata={"recovery": decision.status.value, "message": decision.message},
        )
        audit.append(event)
        state.last_event_sequence = seq
        state.updated_at = utc_now()
        store.save_run(state)
    return decision

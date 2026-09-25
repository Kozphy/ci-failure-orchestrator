"""Phase 10 — durable persistence facade.

``RunPersistence`` checkpoints run state, audit events and evidence for the
runner. The storage, recovery and human-decision implementations live in
``durable``, ``recovery`` and ``human_decision``; this module re-exports them
so ``foundation.persistence`` stays the stable import path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .durable import (
    AUDIT_SCHEMA,
    DURABLE_SCHEMA,
    AuditEvent,
    AuditEventType,
    AuditStore,
    ConsistencyIssue,
    ConsistencyReport,
    DurableEvidenceRef,
    DurableRunState,
    EvidenceLimits,
    EvidenceStore,
    FileAuditStore,
    FileEvidenceStore,
    FileStateStore,
    HumanDecisionResult,
    HumanDecisionStatus,
    PersistenceError,
    RecoveryDecision,
    RecoveryStatus,
    RunInspection,
    StateStore,
    UnsupportedSchemaError,
    atomic_write_text,
    canonical_json,
    sanitize_text_bounded,
    sanitize_value,
)
from .human_decision import append_operator_event, apply_reviewer_decision
from .models import RunStatus, new_id, utc_now
from .recovery import assess_recovery, inspect_run, replay_events, resume_run, verify_run_consistency

__all__ = [
    "AUDIT_SCHEMA",
    "DURABLE_SCHEMA",
    "AuditEvent",
    "AuditEventType",
    "AuditStore",
    "ConsistencyIssue",
    "ConsistencyReport",
    "DurableEvidenceRef",
    "DurableRunState",
    "EvidenceLimits",
    "EvidenceStore",
    "FileAuditStore",
    "FileEvidenceStore",
    "FileStateStore",
    "HumanDecisionResult",
    "HumanDecisionStatus",
    "PersistenceError",
    "RecoveryDecision",
    "RecoveryStatus",
    "RunInspection",
    "RunPersistence",
    "StateStore",
    "UnsupportedSchemaError",
    "append_operator_event",
    "apply_reviewer_decision",
    "assess_recovery",
    "atomic_write_text",
    "canonical_json",
    "inspect_run",
    "replay_events",
    "resume_run",
    "sanitize_text_bounded",
    "sanitize_value",
    "verify_run_consistency",
]


class RunPersistence:
    """Facade used by the orchestrator: checkpoint state + audit + evidence."""

    def __init__(
        self,
        artifacts_root: Path,
        *,
        limits: EvidenceLimits | None = None,
        actor: str = "orchestrator",
    ) -> None:
        self.artifacts_root = Path(artifacts_root)
        self.state_store = FileStateStore(self.artifacts_root)
        self.audit_store = FileAuditStore(self.artifacts_root)
        self.evidence_store = FileEvidenceStore(self.artifacts_root, limits=limits)
        self.limits = limits or EvidenceLimits()
        self.actor = actor
        self._durable: DurableRunState | None = None

    @property
    def durable(self) -> DurableRunState:
        if self._durable is None:
            raise PersistenceError("durable run not initialized")
        return self._durable

    def start_run(self, run_id: str, workflow_status: str = RunStatus.RECEIVED.value) -> DurableRunState:
        durable = DurableRunState(
            schema_version=DURABLE_SCHEMA,
            run_id=run_id,
            workflow_status=workflow_status,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.state_store.create_run(durable)
        self._durable = durable
        self.emit(
            AuditEventType.RUN_CREATED,
            state_before=None,
            state_after=workflow_status,
        )
        return durable

    def emit(
        self,
        event_type: AuditEventType | str,
        *,
        state_before: str | None = None,
        state_after: str | None = None,
        evidence_refs: tuple[DurableEvidenceRef, ...] = (),
        metadata: dict[str, Any] | None = None,
        component: str = "foundation",
    ) -> AuditEvent:
        durable = self.durable
        seq = durable.last_event_sequence + 1
        et = event_type.value if isinstance(event_type, AuditEventType) else event_type
        meta_raw = metadata or {}
        sanitized_meta = sanitize_value(meta_raw, limits=self.limits)
        if not isinstance(sanitized_meta, dict):
            sanitized_meta = {"value": sanitized_meta}
        # Drop truncation helper tuples if any leaked
        clean_meta: dict[str, Any] = {}
        for k, v in sanitized_meta.items():
            if isinstance(v, tuple) and len(v) == 4:
                clean_meta[k] = v[0]
            else:
                clean_meta[k] = v
        event = AuditEvent(
            schema_version=AUDIT_SCHEMA,
            event_id=new_id("evt"),
            run_id=durable.run_id,
            sequence=seq,
            timestamp=utc_now(),
            event_type=et,
            actor=self.actor,
            component=component,
            state_before=state_before if state_before is not None else durable.workflow_status,
            state_after=state_after if state_after is not None else durable.workflow_status,
            evidence_refs=evidence_refs,
            metadata=clean_meta,
        )
        self.audit_store.append(event)
        durable.last_event_sequence = seq
        if state_after is not None:
            durable.workflow_status = state_after
        durable.updated_at = utc_now()
        self.state_store.save_run(durable)
        return event

    def checkpoint(
        self,
        *,
        workflow_status: str | None = None,
        technical_status: str | None = None,
        policy_outcome: str | None = None,
        current_attempt: int | None = None,
        stop_reason: str | None = None,
        **refs: str | None,
    ) -> None:
        durable = self.durable
        if workflow_status is not None:
            durable.workflow_status = workflow_status
        if technical_status is not None:
            durable.technical_status = technical_status
        if policy_outcome is not None:
            durable.policy_outcome = policy_outcome
        if current_attempt is not None:
            durable.current_attempt = current_attempt
        if stop_reason is not None:
            durable.stop_reason = stop_reason
        for key, value in refs.items():
            if value is None:
                continue
            if hasattr(durable, key):
                setattr(durable, key, value)
                durable.evidence_index[key] = value
        durable.updated_at = utc_now()
        self.state_store.save_run(durable)

    def write_json(self, kind: str, value: object, *, name: str | None = None) -> DurableEvidenceRef:
        return self.evidence_store.write_json(self.durable.run_id, kind, value, name=name)

    def write_text(
        self,
        kind: str,
        content: str,
        *,
        name: str | None = None,
        max_chars: int | None = None,
    ) -> DurableEvidenceRef:
        return self.evidence_store.write_text(
            self.durable.run_id,
            kind,
            content,
            name=name,
            max_chars=max_chars,
        )

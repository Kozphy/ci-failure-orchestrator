"""Phase 10 — durable run state, append-oriented audit log, evidence store.

Local filesystem only. Append-oriented ≠ cryptographically tamper-proof.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .escalation import ReviewerAction, ReviewerDecision
from .models import SCHEMA_VERSION, RunStatus, new_id, utc_now
from .sanitization import sanitize_text
from .state_machine import FoundationStateMachine, InvalidStateTransition

DURABLE_SCHEMA = "foundation.durable.v1"
AUDIT_SCHEMA = "foundation.audit.v1"


class PersistenceError(RuntimeError):
    """Critical durable-state / audit write failure."""


class UnsupportedSchemaError(ValueError):
    """Durable artifact schema version is not supported."""


class RecoveryStatus(str, Enum):
    RESUMABLE = "RESUMABLE"
    TERMINAL = "TERMINAL"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    INCONSISTENT = "INCONSISTENT"


class AuditEventType(str, Enum):
    RUN_CREATED = "RUN_CREATED"
    RUN_RESUMED = "RUN_RESUMED"
    CONTEXT_BUILT = "CONTEXT_BUILT"
    FAILURE_CLASSIFIED = "FAILURE_CLASSIFIED"
    PLAN_CREATED = "PLAN_CREATED"
    ATTEMPT_STARTED = "ATTEMPT_STARTED"
    TOOL_CALLED = "TOOL_CALLED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    SANDBOX_STARTED = "SANDBOX_STARTED"
    SANDBOX_COMPLETED = "SANDBOX_COMPLETED"
    EVALUATION_COMPLETED = "EVALUATION_COMPLETED"
    RETRY_DECIDED = "RETRY_DECIDED"
    RETRY_STARTED = "RETRY_STARTED"
    RETRY_STOPPED = "RETRY_STOPPED"
    POLICY_REVIEW_STARTED = "POLICY_REVIEW_STARTED"
    POLICY_APPROVED = "POLICY_APPROVED"
    POLICY_REJECTED = "POLICY_REJECTED"
    POLICY_ESCALATED = "POLICY_ESCALATED"
    ESCALATION_PACKAGE_CREATED = "ESCALATION_PACKAGE_CREATED"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    HUMAN_DECISION_RECORDED = "HUMAN_DECISION_RECORDED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    HUMAN_REJECTED = "HUMAN_REJECTED"
    TARGET_PATCH_APPLIED = "TARGET_PATCH_APPLIED"
    TARGET_BRANCH_PUSHED = "TARGET_BRANCH_PUSHED"
    TARGET_PR_OPENED = "TARGET_PR_OPENED"
    RUN_SUCCEEDED = "RUN_SUCCEEDED"
    RUN_FAILED = "RUN_FAILED"
    PERSISTENCE_ERROR = "PERSISTENCE_ERROR"


class HumanDecisionStatus(str, Enum):
    APPLIED = "APPLIED"
    RECORDED = "RECORDED"
    BLOCKED = "BLOCKED"
    INCONSISTENT = "INCONSISTENT"


@dataclass(frozen=True)
class EvidenceLimits:
    max_stdout_chars: int = 50_000
    max_stderr_chars: int = 50_000
    max_log_chars: int = 100_000
    max_patch_chars: int = 50_000
    max_metadata_chars: int = 8_000


@dataclass(frozen=True)
class DurableEvidenceRef:
    kind: str
    ref: str  # relative to run root
    content_type: str = "application/json"


@dataclass(frozen=True)
class AuditEvent:
    schema_version: str
    event_id: str
    run_id: str
    sequence: int
    timestamp: str
    event_type: str
    actor: str
    component: str
    state_before: str | None
    state_after: str | None
    evidence_refs: tuple[DurableEvidenceRef, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "actor": self.actor,
            "component": self.component,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "evidence_refs": [
                {"kind": r.kind, "ref": r.ref, "content_type": r.content_type}
                for r in self.evidence_refs
            ],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEvent":
        refs = tuple(
            DurableEvidenceRef(
                kind=str(r.get("kind") or ""),
                ref=str(r.get("ref") or ""),
                content_type=str(r.get("content_type") or "application/json"),
            )
            for r in (data.get("evidence_refs") or [])
        )
        return cls(
            schema_version=str(data.get("schema_version") or AUDIT_SCHEMA),
            event_id=str(data["event_id"]),
            run_id=str(data["run_id"]),
            sequence=int(data["sequence"]),
            timestamp=str(data.get("timestamp") or ""),
            event_type=str(data["event_type"]),
            actor=str(data.get("actor") or "orchestrator"),
            component=str(data.get("component") or "foundation"),
            state_before=data.get("state_before"),
            state_after=data.get("state_after"),
            evidence_refs=refs,
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class DurableRunState:
    """Filesystem-persisted run snapshot (refs, not large evidence bodies)."""

    schema_version: str
    run_id: str
    workflow_status: str
    technical_status: str | None = None
    policy_outcome: str | None = None
    current_attempt: int = 0
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    failure_event_ref: str | None = None
    classification_ref: str | None = None
    current_plan_ref: str | None = None
    current_proposal_ref: str | None = None
    latest_evaluation_ref: str | None = None
    latest_policy_decision_ref: str | None = None
    latest_retry_decision_ref: str | None = None
    escalation_ref: str | None = None
    reviewer_decision_ref: str | None = None
    last_event_sequence: int = 0
    stop_reason: str | None = None
    evidence_index: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "workflow_status": self.workflow_status,
            "technical_status": self.technical_status,
            "policy_outcome": self.policy_outcome,
            "current_attempt": self.current_attempt,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "failure_event_ref": self.failure_event_ref,
            "classification_ref": self.classification_ref,
            "current_plan_ref": self.current_plan_ref,
            "current_proposal_ref": self.current_proposal_ref,
            "latest_evaluation_ref": self.latest_evaluation_ref,
            "latest_policy_decision_ref": self.latest_policy_decision_ref,
            "latest_retry_decision_ref": self.latest_retry_decision_ref,
            "escalation_ref": self.escalation_ref,
            "reviewer_decision_ref": self.reviewer_decision_ref,
            "last_event_sequence": self.last_event_sequence,
            "stop_reason": self.stop_reason,
            "evidence_index": dict(self.evidence_index),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DurableRunState":
        version = str(data.get("schema_version") or "")
        if version and version not in {DURABLE_SCHEMA, "1.0", SCHEMA_VERSION}:
            # Accept foundation.v1 aliases only for documented durable schema
            if not version.startswith("foundation.durable"):
                raise UnsupportedSchemaError(f"unsupported durable schema: {version}")
        if version == "1.0":
            data = {**data, "schema_version": DURABLE_SCHEMA}
        return cls(
            schema_version=str(data.get("schema_version") or DURABLE_SCHEMA),
            run_id=str(data["run_id"]),
            workflow_status=str(data["workflow_status"]),
            technical_status=data.get("technical_status"),
            policy_outcome=data.get("policy_outcome"),
            current_attempt=int(data.get("current_attempt") or 0),
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            failure_event_ref=data.get("failure_event_ref"),
            classification_ref=data.get("classification_ref"),
            current_plan_ref=data.get("current_plan_ref"),
            current_proposal_ref=data.get("current_proposal_ref"),
            latest_evaluation_ref=data.get("latest_evaluation_ref"),
            latest_policy_decision_ref=data.get("latest_policy_decision_ref"),
            latest_retry_decision_ref=data.get("latest_retry_decision_ref"),
            escalation_ref=data.get("escalation_ref"),
            reviewer_decision_ref=data.get("reviewer_decision_ref"),
            last_event_sequence=int(data.get("last_event_sequence") or 0),
            stop_reason=data.get("stop_reason"),
            evidence_index=dict(data.get("evidence_index") or {}),
        )


@dataclass(frozen=True)
class ConsistencyIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ConsistencyReport:
    valid: bool
    issues: tuple[ConsistencyIssue, ...] = ()


@dataclass(frozen=True)
class RecoveryDecision:
    status: RecoveryStatus
    run_id: str
    workflow_status: str
    message: str
    last_sequence: int = 0


@dataclass(frozen=True)
class HumanDecisionResult:
    """Outcome of an explicit human reviewer decision (never auto-applied)."""

    status: HumanDecisionStatus
    run_id: str
    workflow_status_before: str
    workflow_status_after: str
    action: str
    message: str
    last_sequence: int = 0
    primary_workspace_mutated: bool = False


@dataclass(frozen=True)
class RunInspection:
    run_id: str
    workflow_status: str
    technical_status: str | None
    policy_outcome: str | None
    current_attempt: int
    last_event: str | None
    last_sequence: int
    created_at: str
    updated_at: str
    evidence_root: str


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return obj.as_posix()
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n"


def sanitize_value(value: Any, *, limits: EvidenceLimits | None = None) -> Any:
    """Recursively sanitize strings in JSON-compatible structures."""

    limits = limits or EvidenceLimits()
    if isinstance(value, str):
        cleaned, _ = sanitize_text(value)
        if len(cleaned) > limits.max_metadata_chars:
            return (
                cleaned[: limits.max_metadata_chars - 24]
                + "\n...[truncated]"
            ), True, len(value), limits.max_metadata_chars
        return cleaned
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            sv = sanitize_value(v, limits=limits)
            if isinstance(sv, tuple) and len(sv) == 4 and sv[1] is True:
                text, _, orig, stored = sv
                out[k] = text
                out[f"{k}__truncation"] = {
                    "truncated": True,
                    "original_length": orig,
                    "stored_length": stored,
                }
            else:
                out[k] = sv
        return out
    if isinstance(value, (list, tuple)):
        return [sanitize_value(v, limits=limits) for v in value]
    if isinstance(value, Enum):
        return value.value
    return value


def sanitize_text_bounded(
    text: str,
    *,
    max_chars: int,
) -> tuple[str, dict[str, Any]]:
    cleaned, _ = sanitize_text(text or "")
    meta: dict[str, Any] = {
        "truncated": False,
        "original_length": len(text or ""),
        "stored_length": len(cleaned),
    }
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max(0, max_chars - 24)] + "\n...[truncated]"
        meta["truncated"] = True
        meta["stored_length"] = len(cleaned)
    return cleaned, meta


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class StateStore(Protocol):
    def create_run(self, run: DurableRunState) -> None: ...

    def load_run(self, run_id: str) -> DurableRunState: ...

    def save_run(self, run: DurableRunState) -> None: ...

    def exists(self, run_id: str) -> bool: ...


class AuditStore(Protocol):
    def append(self, event: AuditEvent) -> None: ...

    def read_events(self, run_id: str) -> list[AuditEvent]: ...

    def latest_sequence(self, run_id: str) -> int: ...


class EvidenceStore(Protocol):
    def write_json(self, run_id: str, kind: str, value: object, *, name: str | None = None) -> DurableEvidenceRef: ...

    def write_text(self, run_id: str, kind: str, content: str, *, name: str | None = None) -> DurableEvidenceRef: ...


class FileStateStore:
    def __init__(self, artifacts_root: Path) -> None:
        self.root = Path(artifacts_root)

    def _path(self, run_id: str) -> Path:
        return self.root / "runs" / run_id / "state.json"

    def exists(self, run_id: str) -> bool:
        return self._path(run_id).is_file()

    def create_run(self, run: DurableRunState) -> None:
        if self.exists(run.run_id):
            raise PersistenceError(f"run already exists: {run.run_id}")
        self.save_run(run)

    def save_run(self, run: DurableRunState) -> None:
        run.updated_at = utc_now()
        try:
            atomic_write_text(self._path(run.run_id), canonical_json(run.to_dict()))
        except OSError as exc:
            raise PersistenceError(f"failed to save run state: {exc}") from exc

    def load_run(self, run_id: str) -> DurableRunState:
        path = self._path(run_id)
        if not path.is_file():
            raise FileNotFoundError(f"run not found: {run_id}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PersistenceError(f"malformed state.json for {run_id}: {exc}") from exc
        if not isinstance(raw, dict):
            raise PersistenceError(f"state.json must be an object for {run_id}")
        return DurableRunState.from_dict(raw)


class FileAuditStore:
    def __init__(self, artifacts_root: Path) -> None:
        self.root = Path(artifacts_root)
        self._seen_ids: dict[str, set[str]] = {}

    def _path(self, run_id: str) -> Path:
        return self.root / "runs" / run_id / "events.jsonl"

    def latest_sequence(self, run_id: str) -> int:
        events, _ = self._read_raw(run_id)
        return events[-1].sequence if events else 0

    def append(self, event: AuditEvent) -> None:
        if event.schema_version != AUDIT_SCHEMA:
            raise UnsupportedSchemaError(event.schema_version)
        seen = self._seen_ids.setdefault(event.run_id, set())
        # Load existing IDs once per process for duplicate detection
        if not seen:
            existing, _ = self._read_raw(event.run_id)
            seen.update(e.event_id for e in existing)
        if event.event_id in seen:
            raise PersistenceError(f"duplicate event_id: {event.event_id}")
        last = self.latest_sequence(event.run_id)
        if event.sequence != last + 1:
            raise PersistenceError(
                f"non-monotonic sequence: expected {last + 1}, got {event.sequence}"
            )
        path = self._path(event.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.to_dict(), sort_keys=True, default=_json_default)
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
        except OSError as exc:
            raise PersistenceError(f"failed to append audit event: {exc}") from exc
        seen.add(event.event_id)

    def read_events(self, run_id: str) -> list[AuditEvent]:
        events, trailing_corrupt = self._read_raw(run_id)
        if trailing_corrupt:
            raise PersistenceError(
                f"malformed trailing audit record in events.jsonl for {run_id}"
            )
        return events

    def read_events_tolerant(self, run_id: str) -> tuple[list[AuditEvent], bool]:
        """Return (events, trailing_corrupt). Valid preceding events are preserved."""

        return self._read_raw(run_id)

    def _read_raw(self, run_id: str) -> tuple[list[AuditEvent], bool]:
        path = self._path(run_id)
        if not path.is_file():
            return [], False
        events: list[AuditEvent] = []
        trailing_corrupt = False
        lines = path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                events.append(AuditEvent.from_dict(data))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                # Only treat as recoverable trailing corruption if last non-empty line
                if idx == len(lines) - 1:
                    trailing_corrupt = True
                    break
                raise PersistenceError(
                    f"corrupt audit event at line {idx + 1} for {run_id}"
                )
        return events, trailing_corrupt


class FileEvidenceStore:
    KIND_DIRS = {
        "input": "input",
        "classification": "classification",
        "plan": "plans",
        "attempt": "attempts",
        "proposal": "proposals",
        "patch": "proposals",
        "sandbox": "sandbox",
        "evaluation": "evaluations",
        "retry": "retry",
        "policy": "policy",
        "escalation": "escalation",
        "reviewer": "reviewer",
        "tool": "tools",
        "target": "target",
    }

    def __init__(self, artifacts_root: Path, limits: EvidenceLimits | None = None) -> None:
        self.root = Path(artifacts_root)
        self.limits = limits or EvidenceLimits()

    def run_root(self, run_id: str) -> Path:
        return self.root / "runs" / run_id

    def write_json(
        self,
        run_id: str,
        kind: str,
        value: object,
        *,
        name: str | None = None,
    ) -> DurableEvidenceRef:
        rel_dir = self.KIND_DIRS.get(kind, kind)
        filename = name or f"{kind}.json"
        if not filename.endswith(".json"):
            filename = f"{filename}.json"
        rel = f"{rel_dir}/{filename}".replace("\\", "/")
        path = self.run_root(run_id) / rel_dir / filename
        sanitized = sanitize_value(value, limits=self.limits)
        # unwrap accidental truncation tuples at top level
        if isinstance(sanitized, tuple):
            sanitized = sanitized[0]
        try:
            atomic_write_text(path, canonical_json(sanitized))
        except OSError as exc:
            raise PersistenceError(f"failed to write evidence {rel}: {exc}") from exc
        return DurableEvidenceRef(kind=kind, ref=rel, content_type="application/json")

    def write_text(
        self,
        run_id: str,
        kind: str,
        content: str,
        *,
        name: str | None = None,
        max_chars: int | None = None,
    ) -> DurableEvidenceRef:
        rel_dir = self.KIND_DIRS.get(kind, kind)
        filename = name or f"{kind}.txt"
        rel = f"{rel_dir}/{filename}".replace("\\", "/")
        path = self.run_root(run_id) / rel_dir / filename
        bound = max_chars if max_chars is not None else self.limits.max_log_chars
        cleaned, meta = sanitize_text_bounded(content, max_chars=bound)
        try:
            atomic_write_text(path, cleaned)
            if meta["truncated"]:
                meta_path = path.with_suffix(path.suffix + ".truncation.json")
                atomic_write_text(meta_path, canonical_json(meta))
        except OSError as exc:
            raise PersistenceError(f"failed to write evidence {rel}: {exc}") from exc
        ctype = "text/plain"
        if filename.endswith(".patch"):
            ctype = "text/x-diff"
        elif filename.endswith(".md"):
            ctype = "text/markdown"
        return DurableEvidenceRef(kind=kind, ref=rel, content_type=ctype)


# --- Recovery / inspection / consistency ---

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

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

from .models import SCHEMA_VERSION, utc_now
from .sanitization import sanitize_text

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

"""Phase 2–8 agent execution foundation models.

Human escalation workflows are intentionally out of scope (Phase 9).
Confidence values are heuristic unless documented as calibrated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "foundation.v1"


def utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    """Return a new identifier of the form ``<prefix>-<12 hex characters>``."""
    return f"{prefix}-{uuid4().hex[:12]}"


class ToolRiskLevel(str, Enum):
    """Risk levels assigned to tools."""

    READ_ONLY = "READ_ONLY"
    SAFE_WRITE = "SAFE_WRITE"
    RESTRICTED = "RESTRICTED"


class RunStatus(str, Enum):
    """Foundation lifecycle including Phase 7–9 governance states."""

    RECEIVED = "RECEIVED"
    CONTEXT_READY = "CONTEXT_READY"
    CLASSIFIED = "CLASSIFIED"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    PROPOSAL_READY = "PROPOSAL_READY"
    SANDBOX_RUNNING = "SANDBOX_RUNNING"
    EVALUATING = "EVALUATING"
    EVALUATED = "EVALUATED"
    RETRY_DECISION = "RETRY_DECISION"
    RETRYING = "RETRYING"
    POLICY_REVIEW = "POLICY_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    ESCALATION_BUILDING = "ESCALATION_BUILDING"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    ESCALATION_ERROR = "ESCALATION_ERROR"
    # Legacy technical-success terminal (Phase 2–7). Phase 8+ uses APPROVED.
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class CheckStatus(str, Enum):
    """Outcomes of an evaluation check."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"
    UNAVAILABLE = "UNAVAILABLE"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class FailureEvent:
    """CI failure received for repair."""

    event_id: str
    run_id: str
    source: str
    workflow: str
    job: str
    failed_step: str
    message: str
    repository: str = ""
    commit_sha: str = ""
    branch: str = ""
    exit_code: int | None = None
    changed_paths: tuple[str, ...] = ()
    log_excerpt: str = ""
    raw_log_ref: str = ""
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return the event as a dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, run_id: str | None = None) -> "FailureEvent":
        """Build an event from a dict, generating IDs and defaults for missing fields.

        A non-empty ``run_id`` argument overrides the dict's run ID.
        """

        return cls(
            event_id=str(data.get("event_id") or new_id("evt")),
            run_id=run_id or str(data.get("run_id") or new_id("run")),
            source=str(data.get("source") or "fixture"),
            workflow=str(data.get("workflow") or "ci"),
            job=str(data.get("job") or "test"),
            failed_step=str(data.get("failed_step") or "unknown"),
            message=str(data.get("message") or ""),
            repository=str(data.get("repository") or ""),
            commit_sha=str(data.get("commit_sha") or ""),
            branch=str(data.get("branch") or ""),
            exit_code=data.get("exit_code"),
            changed_paths=tuple(data.get("changed_paths") or ()),
            log_excerpt=str(data.get("log_excerpt") or ""),
            raw_log_ref=str(data.get("raw_log_ref") or ""),
        )


@dataclass(frozen=True)
class FailureContext:
    """Bounded summary and prioritized evidence for one failure."""

    run_id: str
    event_id: str
    summary: str
    prioritized_evidence: tuple[str, ...]
    changed_paths: tuple[str, ...]
    truncated: bool = False
    truncation_reasons: tuple[str, ...] = ()
    redactions_applied: int = 0
    char_count: int = 0
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class FailureClassification:
    """Heuristic classification (confidence is not calibrated)."""

    run_id: str
    category: str
    evidence: tuple[str, ...]
    confidence: float
    uncertainty: str
    recommended_next_action: str = "plan_minimal_repair"
    calibrated: bool = False
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class PlanStep:
    """One tool invocation in a repair plan."""

    step_id: str
    action: str
    tool: str
    inputs: dict[str, Any] = field(default_factory=dict)
    risk_level: ToolRiskLevel = ToolRiskLevel.READ_ONLY


@dataclass(frozen=True)
class RepairPlan:
    """Planned repair steps, verification steps and stop conditions for a run."""

    run_id: str
    goal: str
    assumptions: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    required_tools: tuple[str, ...]
    risk_level: str
    verification_steps: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class ToolCall:
    """Record of one tool invocation request."""

    call_id: str
    run_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk_level: ToolRiskLevel
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class ToolResult:
    """Outcome of one tool invocation."""

    tool_name: str
    success: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""
    run_id: str = ""
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class RepairProposal:
    """Proposed patch with its rationale and verification plan."""

    proposal_id: str
    run_id: str
    files_changed: tuple[str, ...]
    patch: str
    rationale: str
    expected_effect: str
    verification_plan: tuple[str, ...]
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of running a proposal in a sandbox."""

    run_id: str
    proposal_id: str
    success: bool
    patch_applied: bool
    command_results: tuple[ToolResult, ...]
    changed_files: tuple[str, ...]
    timeout: bool = False
    error: str | None = None
    workspace: str = ""
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class EvaluationCheck:
    """Result of one evaluation check."""

    name: str
    status: CheckStatus
    detail: str = ""


@dataclass(frozen=True)
class EvaluationResult:
    """Technical evaluation of a sandboxed proposal."""

    run_id: str
    passed: bool
    patch_applied: bool
    target_verification_passed: bool
    regressions_detected: bool
    forbidden_changes_detected: bool
    checks: tuple[EvaluationCheck, ...]
    evidence: tuple[str, ...]
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass
class RunState:
    """Mutable in-memory state of one orchestrator run."""

    run_id: str
    status: RunStatus = RunStatus.RECEIVED
    event: FailureEvent | None = None
    context: FailureContext | None = None
    classification: FailureClassification | None = None
    plan: RepairPlan | None = None
    proposal: RepairProposal | None = None
    sandbox: SandboxResult | None = None
    evaluation: EvaluationResult | None = None
    attempts: list[Any] = field(default_factory=list)
    attempt_count: int = 0
    retry_count: int = 0
    stop_reason: str | None = None
    last_retry_decision: dict[str, Any] | None = None
    retry_trace: list[str] = field(default_factory=list)
    technical_status: str | None = None  # PASS | FAIL
    policy_outcome: str | None = None
    policy_decision: Any | None = None
    policy_trace: list[str] = field(default_factory=list)
    escalation: Any | None = None
    escalation_id: str | None = None
    artifact_refs: dict[str, str] = field(default_factory=dict)
    workflow_status: str | None = None
    updated_at: str = field(default_factory=utc_now)

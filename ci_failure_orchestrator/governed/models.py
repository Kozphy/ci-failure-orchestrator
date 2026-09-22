"""Canonical domain models for the governed agent pipeline.

These types are the integration contract for ``governed.pipeline``.
Existing stacks (supervisor, agent_loop, trust_gateway) remain supported;
adapters map to/from these models where needed.

Confidence fields are **heuristic** unless a calibrated model is attached.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = "governed.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


class ToolRiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    SAFE_WRITE = "SAFE_WRITE"
    RESTRICTED = "RESTRICTED"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


class PolicyOutcome(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"
    RETRY = "RETRY"


class PipelineState(str, Enum):
    RECEIVED = "RECEIVED"
    CONTEXT_READY = "CONTEXT_READY"
    CLASSIFIED = "CLASSIFIED"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    EVALUATING = "EVALUATING"
    RETRYING = "RETRYING"
    POLICY_REVIEW = "POLICY_REVIEW"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    APPROVED = "APPROVED"
    APPLYING = "APPLYING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class FailureEvent:
    """Normalized CI failure ingress event."""

    event_id: str
    run_id: str
    source: str
    workflow: str
    job: str
    failed_step: str
    message: str
    changed_paths: tuple[str, ...] = ()
    log_excerpt: str = ""
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FailureContext:
    """Budgeted, sanitized context for planning and tool use."""

    run_id: str
    event_id: str
    summary: str
    prioritized_evidence: tuple[str, ...]
    changed_paths: tuple[str, ...]
    previous_attempts: tuple[dict[str, Any], ...] = ()
    token_estimate: int = 0
    redactions_applied: int = 0
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class FailureClassification:
    """Failure label with heuristic confidence (not calibrated unless noted)."""

    run_id: str
    failure_class: str
    confidence: float
    evidence: tuple[str, ...]
    uncertainty: str
    recommended_next_action: str
    calibrated: bool = False
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class PlanStep:
    name: str
    tool_name: str
    intent: str
    risk_level: ToolRiskLevel = ToolRiskLevel.READ_ONLY


@dataclass(frozen=True)
class RepairPlan:
    run_id: str
    goal: str
    assumptions: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    required_tools: tuple[str, ...]
    risk_level: str
    expected_verification: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    run_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk_level: ToolRiskLevel
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    run_id: str
    tool_name: str
    ok: bool
    output: dict[str, Any]
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class RepairProposal:
    proposal_id: str
    run_id: str
    files_affected: tuple[str, ...]
    proposed_patch: str
    reasoning_summary: str
    expected_impact: str
    risk_classification: str
    verification_plan: tuple[str, ...]
    rollback: str
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class SandboxResult:
    run_id: str
    proposal_id: str
    applied: bool
    commands_run: tuple[str, ...]
    stdout_excerpt: str
    stderr_excerpt: str
    timed_out: bool = False
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class EvaluationResult:
    run_id: str
    passed: bool
    target_check_passed: bool
    regression_free: bool
    policy_safe: bool
    evidence: tuple[str, ...]
    score: float | None = None
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class RetryDecision:
    run_id: str
    should_retry: bool
    attempts_used: int
    max_attempts: int
    reason: str
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class PolicyDecision:
    run_id: str
    outcome: PolicyOutcome
    reasons: tuple[str, ...]
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class HumanEscalation:
    run_id: str
    why: str
    failure_summary: str
    attempted_repairs: tuple[str, ...]
    proposed_change: str
    evaluation_evidence: tuple[str, ...]
    remaining_uncertainty: str
    recommended_review_action: str
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class VerificationResult:
    run_id: str
    verified: bool
    checks: tuple[str, ...]
    evidence: tuple[str, ...]
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    run_id: str
    event_type: str
    actor: str
    decision: str | None
    reason: str
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    timestamp: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

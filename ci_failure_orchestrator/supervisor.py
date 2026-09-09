"""Policy-driven supervisor for delegating CI repairs to bounded agents.

The supervisor is intentionally provider-agnostic. It decides *whether* an external
repair worker (for example Copilot, a coding agent, or a custom executor) may act,
what authority it receives, and when autonomy must stop. It does not execute shell,
Git, deployment, or merge operations itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Iterable


class RiskLevel(str, Enum):
    """Risk assigned to a candidate repair."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RepairAuthority(str, Enum):
    """Maximum authority granted to a repair worker."""

    AUTONOMOUS_PATCH = "autonomous_patch"
    PATCH_REQUIRES_REVIEW = "patch_requires_review"
    RCA_ONLY = "rca_only"
    DENY = "deny"


@dataclass(frozen=True)
class RetryBudget:
    """Hard autonomy limits for one incident."""

    max_attempts: int = 3
    max_changed_files: int = 8
    max_changed_lines: int = 400
    max_cost_usd: float = 2.0
    max_elapsed_seconds: int = 900

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.max_changed_files < 1 or self.max_changed_lines < 1:
            raise ValueError("change budgets must be positive")
        if self.max_cost_usd < 0 or self.max_elapsed_seconds < 1:
            raise ValueError("cost/time budgets must be non-negative/positive")


@dataclass(frozen=True)
class RepairRequest:
    """Evidence used to decide whether an agent may mutate a pull request."""

    failure_class: str
    changed_paths: tuple[str, ...] = ()
    predicted_changed_lines: int = 0
    attempt: int = 1
    cost_spent_usd: float = 0.0
    elapsed_seconds: int = 0
    regression_detected: bool = False
    security_finding: bool = False
    test_weakening_detected: bool = False
    unknown_failure: bool = False


@dataclass(frozen=True)
class SupervisorDecision:
    """Machine-readable decision returned before agent execution."""

    risk: RiskLevel
    authority: RepairAuthority
    allowed: bool
    reasons: tuple[str, ...] = ()
    required_gates: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class SupervisorPolicy:
    """Repository-level repair policy and safety invariants."""

    budget: RetryBudget = field(default_factory=RetryBudget)
    protected_globs: tuple[str, ...] = (
        ".github/workflows/*",
        "**/migrations/*",
        "**/auth/*",
        "**/iam/*",
        "**/security/*",
        "infra/*",
        "terraform/*",
    )
    critical_globs: tuple[str, ...] = (
        "**/*secret*",
        "**/*credential*",
        "**/*production*",
        "**/*prod*",
    )
    low_risk_failure_classes: tuple[str, ...] = (
        "lint",
        "formatting",
        "typing",
        "deterministic_test_fixture",
        "workflow_syntax",
    )
    forbidden_actions: tuple[str, ...] = (
        "delete_failing_tests",
        "disable_required_checks",
        "add_continue_on_error_to_hide_failure",
        "lower_coverage_threshold_without_policy_approval",
        "disable_security_scanner",
        "expose_or_modify_secrets",
        "force_merge",
    )


def _matches(path: str, patterns: Iterable[str]) -> bool:
    """Return True when a repository path matches any policy glob."""

    normalized = path.replace("\\", "/").lstrip("./")
    p = PurePosixPath(normalized)
    return any(p.match(pattern) for pattern in patterns)


def classify_risk(request: RepairRequest, policy: SupervisorPolicy) -> RiskLevel:
    """Classify repair risk from failure type, paths, and security evidence."""

    if request.security_finding or any(
        _matches(path, policy.critical_globs) for path in request.changed_paths
    ):
        return RiskLevel.CRITICAL

    if any(_matches(path, policy.protected_globs) for path in request.changed_paths):
        return RiskLevel.HIGH

    if request.unknown_failure or request.failure_class not in policy.low_risk_failure_classes:
        return RiskLevel.MEDIUM

    return RiskLevel.LOW


def evaluate_repair(request: RepairRequest, policy: SupervisorPolicy | None = None) -> SupervisorDecision:
    """Return the maximum safe authority for a proposed CI repair.

    The function fails closed. Regression evidence, test weakening, or exhausted
    autonomy budgets deny mutation regardless of the nominal failure class.
    """

    policy = policy or SupervisorPolicy()
    reasons: list[str] = []

    if request.regression_detected:
        reasons.append("regression_detected")
    if request.test_weakening_detected:
        reasons.append("test_weakening_detected")
    if request.attempt > policy.budget.max_attempts:
        reasons.append("retry_budget_exhausted")
    if len(request.changed_paths) > policy.budget.max_changed_files:
        reasons.append("changed_file_budget_exhausted")
    if request.predicted_changed_lines > policy.budget.max_changed_lines:
        reasons.append("changed_line_budget_exhausted")
    if request.cost_spent_usd > policy.budget.max_cost_usd:
        reasons.append("cost_budget_exhausted")
    if request.elapsed_seconds > policy.budget.max_elapsed_seconds:
        reasons.append("time_budget_exhausted")

    risk = classify_risk(request, policy)

    if reasons:
        return SupervisorDecision(
            risk=risk,
            authority=RepairAuthority.DENY,
            allowed=False,
            reasons=tuple(reasons),
            required_gates=("human_escalation", "root_cause_review"),
            forbidden_actions=policy.forbidden_actions,
        )

    if risk is RiskLevel.CRITICAL:
        return SupervisorDecision(
            risk=risk,
            authority=RepairAuthority.DENY,
            allowed=False,
            reasons=("critical_surface",),
            required_gates=("security_review", "human_approval"),
            forbidden_actions=policy.forbidden_actions,
        )

    if risk is RiskLevel.HIGH:
        return SupervisorDecision(
            risk=risk,
            authority=RepairAuthority.RCA_ONLY,
            allowed=True,
            reasons=("protected_surface",),
            required_gates=("human_approval", "full_regression", "security_gate"),
            forbidden_actions=policy.forbidden_actions,
        )

    if risk is RiskLevel.MEDIUM:
        return SupervisorDecision(
            risk=risk,
            authority=RepairAuthority.PATCH_REQUIRES_REVIEW,
            allowed=True,
            reasons=("nontrivial_change",),
            required_gates=("targeted_tests", "full_regression", "human_review"),
            forbidden_actions=policy.forbidden_actions,
        )

    return SupervisorDecision(
        risk=risk,
        authority=RepairAuthority.AUTONOMOUS_PATCH,
        allowed=True,
        reasons=("bounded_low_risk_repair",),
        required_gates=("targeted_tests", "full_regression", "policy_gate"),
        forbidden_actions=policy.forbidden_actions,
    )

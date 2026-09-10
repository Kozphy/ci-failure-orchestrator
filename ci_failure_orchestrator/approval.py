"""Human approval gating for CI repair release authorization.

This module provides the human approval gate that determines whether a verified
repair requires human review before release authorization. It enforces the
safety invariant that repair agents cannot approve their own release.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ApprovalDecision(str, Enum):
    """Approval decision outcomes for repair release authorization.

    Attributes:
        APPROVED: Repair is approved for release (automated or human-approved).
        REJECTED: Repair is rejected and cannot be released.
        REQUIRED: Human approval is required before release can proceed.
    """

    APPROVED = "approved"
    REJECTED = "rejected"
    REQUIRED = "required"


@dataclass(frozen=True)
class ApprovalContext:
    """Context for evaluating human approval requirements.

    Attributes:
        policy_decision: Decision from the policy layer (e.g., "release", "block").
        evaluation_score: Evaluator score for the repair proposal (0.0 to 1.0).
        regression_free: Whether the repair is regression-free.
        changed_files: Tuple of file paths modified by the repair.
        high_risk_paths: Tuple of high-risk file paths (e.g., .github/, infra/).
    """

    policy_decision: str
    evaluation_score: float
    regression_free: bool
    changed_files: tuple[str, ...]
    high_risk_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovalResult:
    """Result from the human approval gate evaluation.

    Attributes:
        decision: ApprovalDecision (APPROVED, REJECTED, or REQUIRED).
        reason: Human-readable explanation of the decision.
    """

    decision: ApprovalDecision
    reason: str


class HumanApprovalGate:
    """Determines whether a verified repair still requires human approval.

    This gate enforces the safety invariant that repair agents cannot approve
    their own release. It evaluates repair proposals against policy decisions,
    regression status, evaluation scores, and high-risk file paths to determine
    whether human approval is required.

    Attributes:
        score_threshold: Minimum evaluation score for automated approval (default: 0.97).
        high_risk_prefixes: File path prefixes that trigger human approval requirement.

    Audit Notes:
        - Bypassing human approval for high-risk paths could release dangerous changes.
        - Evaluation score below threshold may indicate uncertain repair quality.
        - Recovery: Review approval logs and adjust thresholds if approvals are too restrictive.
        - Evidence: All approval decisions include reasoning and context for audit.

    Engineering Notes:
        - Trade-off: High threshold (0.97) ensures quality but may require frequent human review.
        - Design: High-risk prefixes (.github/, infra/, migrations/, security/) require human approval.
        - Performance: Simple path prefix matching is fast and effective for risk classification.
    """

    def __init__(self, *, score_threshold: float = 0.97, high_risk_prefixes: tuple[str, ...] = (".github/", "infra/", "migrations/", "security/")):
        """Initialize the human approval gate.

        Args:
            score_threshold: Minimum evaluation score for automated approval (default: 0.97).
            high_risk_prefixes: File path prefixes that trigger human approval requirement.
        """
        self.score_threshold = score_threshold
        self.high_risk_prefixes = high_risk_prefixes

    def evaluate(self, context: ApprovalContext, *, human_approved: bool | None = None) -> ApprovalResult:
        """Evaluate whether a repair requires human approval for release.

        This method checks policy decisions, regression status, evaluation scores,
        and high-risk file paths to determine the approval decision. Human approval
        can override automated requirements when explicitly provided.

        Args:
            context: ApprovalContext with policy decision, evaluation score, and file changes.
            human_approved: Optional human approval status (True=approved, False=rejected, None=not provided).

        Returns:
            ApprovalResult with decision (APPROVED, REJECTED, or REQUIRED) and reasoning.

        Evaluation Logic:
            - Reject if policy decision is not "release".
            - Reject if regression is detected.
            - Approve automatically if low-risk and evaluation score meets threshold.
            - Approve if human explicitly approved.
            - Reject if human explicitly rejected.
            - Require human approval for high-risk paths or low evaluation scores.

        Side Effects:
            - None (pure decision logic).

        Safety Invariants:
            - High-risk paths always require human approval.
            - Regression detection always blocks release.
            - Human approval can override automated requirements but not safety invariants.
        """
        if context.policy_decision != "release":
            return ApprovalResult(ApprovalDecision.REJECTED, "policy did not authorize release")
        if not context.regression_free:
            return ApprovalResult(ApprovalDecision.REJECTED, "regression detected")

        risk_paths = tuple(
            path for path in context.changed_files
            if path.startswith(self.high_risk_prefixes)
        )
        requires_human = bool(risk_paths) or context.evaluation_score < self.score_threshold

        if not requires_human:
            return ApprovalResult(ApprovalDecision.APPROVED, "low-risk repair passed automated gate")
        if human_approved is True:
            return ApprovalResult(ApprovalDecision.APPROVED, "human approval recorded")
        if human_approved is False:
            return ApprovalResult(ApprovalDecision.REJECTED, "human rejected repair")
        return ApprovalResult(ApprovalDecision.REQUIRED, "human approval required for elevated risk")

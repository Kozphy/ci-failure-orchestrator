"""Policy engines for CI repair and delivery decisions.

This module provides policy engines that enforce safety gates for autonomous
CI/CD actions, including release authorization, retry budgets, regression
detection, and escalation to human review.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .control_plane import Decision, Evaluation, RunState
from .tournament import CandidateScore, TournamentResult


class Action(str, Enum):
    """Policy action outcomes for delivery-state CI/CD/CT control actions.

    Attributes:
        PASS: Action is approved to proceed.
        RETRY: Action should be retried.
        BLOCK: Action is blocked and cannot proceed.
        ESCALATE: Escalation to human review is required.
        ROLLBACK: Rollback action is required.
    """

    PASS = "PASS"
    RETRY = "RETRY"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"
    ROLLBACK = "ROLLBACK"


@dataclass(frozen=True)
class DeliveryDecision:
    """Policy decision for delivery-state CI/CD/CT control actions.

    Attributes:
        action: Action to take (PASS, RETRY, BLOCK, ESCALATE, or ROLLBACK).
        reason: Human-readable explanation of the decision.
        confidence: Confidence in the decision (0.0 to 1.0).
        evidence: Tuple of evidence tags supporting the decision.
        policy_id: Identifier for the policy version (default: "default-v1").
        retry_budget_remaining: Remaining retry budget (default: 0).
    """

    action: Action
    reason: str
    confidence: float
    evidence: tuple[str, ...] = ()
    policy_id: str = "default-v1"
    retry_budget_remaining: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert the delivery decision to a dictionary representation.

        Returns:
            Dictionary containing all decision fields with action as string value.
        """
        data = asdict(self)
        data["action"] = self.action.value
        return data


@dataclass(frozen=True)
class PolicyContext:
    """Context for policy decision evaluation.

    Attributes:
        failure_class: Classification of the failure type.
        confidence: Confidence in the failure classification (0.0 to 1.0).
        retryable: Whether the failure is retryable.
        retry_count: Number of retry attempts already used (default: 0).
        retry_budget: Maximum number of retry attempts allowed (default: 2).
        repeated_signature: Number of times this error signature has been seen (default: 0).
        ct_regression: Whether continuous testing regression was detected (default: False).
        security_severity: Security severity level if applicable (default: None).
        canary_regression: Whether canary regression was detected (default: False).
    """

    failure_class: str
    confidence: float
    retryable: bool
    retry_count: int = 0
    retry_budget: int = 2
    repeated_signature: int = 0
    ct_regression: bool = False
    security_severity: str | None = None
    canary_regression: bool = False


class PolicyEngine:
    """Deterministic safety gate around autonomous CI/CD actions.

    This policy engine enforces safety rules for delivery-state actions,
    including regression detection, security severity checks, retry budget
    enforcement, and escalation for unknown or dangerous conditions.

    Audit Notes:
        - Bypassing regression detection could release dangerous changes.
        - High-severity security failures must always block release.
        - Retry budget exhaustion prevents infinite retry loops.
        - Recovery: Review policy decisions and adjust thresholds if gates are too restrictive.
        - Evidence: All policy decisions include reasoning and evidence tags for audit.

    Engineering Notes:
        - Trade-off: Fail-closed policy ensures safety but may require frequent human review.
        - Design: Regression and security checks always override retry logic.
        - Performance: Simple rule-based evaluation is fast and deterministic.
    """

    def decide(self, ctx: PolicyContext) -> DeliveryDecision:
        """Make a delivery decision based on policy context.

        This method evaluates the policy context against safety rules and
        returns an action with reasoning and evidence tags.

        Args:
            ctx: PolicyContext with failure classification, retry status, and regression information.

        Returns:
            DeliveryDecision with action, reasoning, confidence, and evidence tags.

        Decision Logic:
            - ROLLBACK if canary regression detected.
            - BLOCK if continuous testing regression detected.
            - BLOCK if high-severity or critical security failure.
            - ESCALATE if diagnosis confidence below threshold (0.60).
            - BLOCK if failure is non-retryable.
            - ESCALATE if retry budget exhausted or signature repeated (>=2).
            - RETRY if failure is retryable within budget.

        Side Effects:
            - None (pure decision logic).

        Safety Invariants:
            - Regression detection always triggers rollback or block.
            - High-severity security failures always block.
            - Retry budget prevents infinite retry loops.
        """
        remaining = max(ctx.retry_budget - ctx.retry_count, 0)
        if ctx.canary_regression:
            return DeliveryDecision(Action.ROLLBACK, "canary regression detected", 1.0, ("canary_regression",), retry_budget_remaining=remaining)
        if ctx.ct_regression:
            return DeliveryDecision(Action.BLOCK, "continuous-testing regression detected", 1.0, ("ct_regression",), retry_budget_remaining=remaining)
        if (ctx.security_severity or "").lower() in {"high", "critical"}:
            return DeliveryDecision(Action.BLOCK, "high-severity security failure", 1.0, (f"security:{ctx.security_severity}",), retry_budget_remaining=remaining)
        if ctx.confidence < 0.60:
            return DeliveryDecision(Action.ESCALATE, "diagnosis confidence below policy threshold", ctx.confidence, ("low_confidence",), retry_budget_remaining=remaining)
        if not ctx.retryable:
            return DeliveryDecision(Action.BLOCK, "deterministic/non-retryable failure", ctx.confidence, (ctx.failure_class,), retry_budget_remaining=remaining)
        if ctx.retry_count >= ctx.retry_budget or ctx.repeated_signature >= 2:
            return DeliveryDecision(Action.ESCALATE, "retry/stopping condition reached", ctx.confidence, ("retry_budget",), retry_budget_remaining=remaining)
        return DeliveryDecision(Action.RETRY, "failure is retryable within budget", ctx.confidence, (ctx.failure_class,), retry_budget_remaining=remaining)


class DefaultRepairPolicy:
    """Fail-closed release policy for the bounded autonomous control plane.

    This policy enforces a fail-closed approach where regression detection
    blocks release, and release requires both passing evaluation and a
    minimum evaluation score.

    Attributes:
        release_score: Minimum evaluation score for release (default: 0.90).
        retry_score: Minimum evaluation score for retry (default: 0.60).

    Audit Notes:
        - Regression detection always blocks release (fail-closed safety).
        - Low evaluation scores prevent release of uncertain repairs.
        - Recovery: Review evaluation scores and adjust thresholds if repairs are too restrictive.
        - Evidence: All policy decisions include evaluation context for audit.

    Engineering Notes:
        - Trade-off: High release threshold (0.90) ensures quality but may require frequent human review.
        - Design: Regression check overrides score-based decisions.
        - Performance: Simple threshold-based evaluation is fast and deterministic.
    """

    def __init__(self, *, release_score: float = 0.90, retry_score: float = 0.60) -> None:
        """Initialize the default repair policy.

        Args:
            release_score: Minimum evaluation score for release (default: 0.90).
            retry_score: Minimum evaluation score for retry (default: 0.60).
        """
        self.release_score = release_score
        self.retry_score = retry_score

    def decide(self, evaluation: Evaluation, state: RunState) -> Decision:
        """Make a repair policy decision based on evaluation and state.

        Args:
            evaluation: Evaluation result for the repair proposal.
            state: Current run state with budget and retry information.

        Returns:
            Decision (RELEASE, RETRY, BLOCK, or ESCALATE).

        Decision Logic:
            - BLOCK if regression detected.
            - RELEASE if evaluation passed and score meets release threshold.
            - RETRY if score meets retry threshold.
            - ESCALATE otherwise.

        Side Effects:
            - None (pure decision logic).

        Safety Invariants:
            - Regression detection always blocks release.
            - Evaluation score thresholds prevent uncertain repairs.
        """
        if not evaluation.regression_free:
            return Decision.BLOCK
        if evaluation.passed and evaluation.score >= self.release_score:
            return Decision.RELEASE
        if evaluation.score >= self.retry_score:
            return Decision.RETRY
        return Decision.ESCALATE


@dataclass(frozen=True)
class PolicyDecision:
    """Policy decision for tournament-selected repairs.

    Attributes:
        action: Action to take (e.g., "ESCALATE_HUMAN", "READY_FOR_CANARY").
        reason: Human-readable explanation of the decision.
        requires_human_approval: Whether human approval is required.
    """

    action: str
    reason: str
    requires_human_approval: bool


class RepairPolicyGate:
    """Final release boundary for tournament-selected, independently evaluated repairs.

    This gate enforces risk, cost, and latency limits on tournament-winning
    repair candidates before they proceed to canary deployment or human approval.

    Attributes:
        max_risk_score: Maximum acceptable risk score (default: 0.6).
        max_cost_usd: Maximum acceptable cost in USD (default: 0.50).
        max_latency_ms: Maximum acceptable latency in milliseconds (default: 60,000).

    Audit Notes:
        - Bypassing risk, cost, or latency limits could release dangerous or expensive repairs.
        - Missing independent evaluation always blocks release.
        - Recovery: Review tournament results and adjust limits if gates are too restrictive.
        - Evidence: All policy decisions include tournament result context for audit.

    Engineering Notes:
        - Trade-off: Strict limits ensure safety but may reject valid repairs.
        - Design: Independent evaluation is required before policy gate.
        - Performance: Simple threshold-based evaluation is fast and deterministic.
    """

    def __init__(
        self,
        *,
        max_risk_score: float = 0.6,
        max_cost_usd: float = 0.50,
        max_latency_ms: int = 60_000,
    ) -> None:
        """Initialize the repair policy gate.

        Args:
            max_risk_score: Maximum acceptable risk score (default: 0.6).
            max_cost_usd: Maximum acceptable cost in USD (default: 0.50).
            max_latency_ms: Maximum acceptable latency in milliseconds (default: 60,000).
        """
        self.max_risk_score = max_risk_score
        self.max_cost_usd = max_cost_usd
        self.max_latency_ms = max_latency_ms

    def decide(self, result: TournamentResult) -> PolicyDecision:
        """Make a policy decision based on tournament result.

        Args:
            result: TournamentResult with winning candidate and evaluation results.

        Returns:
            PolicyDecision with action, reasoning, and human approval requirement.

        Decision Logic:
            - ESCALATE_HUMAN if no winner, winner not accepted, or action not ready.
            - HUMAN_APPROVAL_REQUIRED if winner exceeds risk, cost, or latency limits.
            - BLOCK if winner lacks successful independent evaluation.
            - READY_FOR_CANARY if winner passed evaluation and automated policy limits.

        Side Effects:
            - None (pure decision logic).

        Safety Invariants:
            - Independent evaluation is required before policy gate.
            - Risk, cost, and latency limits enforce bounded autonomy.
        """
        winner = result.winner
        if (
            winner is None
            or not winner.accepted
            or result.action != "READY_FOR_POLICY_GATE"
        ):
            return PolicyDecision("ESCALATE_HUMAN", result.reason, True)
        if not self._within_budget(winner):
            return PolicyDecision(
                "HUMAN_APPROVAL_REQUIRED",
                "winning candidate exceeds automated risk, cost, or latency policy",
                True,
            )
        if winner.evaluation is None or not winner.evaluation.success:
            return PolicyDecision(
                "BLOCK",
                "winning candidate lacks successful independent evaluation",
                True,
            )
        return PolicyDecision(
            "READY_FOR_CANARY",
            "winning candidate passed evaluation and automated policy limits",
            False,
        )

    def _within_budget(self, candidate: CandidateScore) -> bool:
        """Check if candidate is within risk, cost, and latency limits.

        Args:
            candidate: CandidateScore with risk, cost, and latency metrics.

        Returns:
            True if candidate is within all limits, False otherwise.
        """
        return (
            0 <= candidate.risk_score <= self.max_risk_score
            and 0 <= candidate.cost_usd <= self.max_cost_usd
            and 0 <= candidate.latency_ms <= self.max_latency_ms
        )

from __future__ import annotations

"""Policy decision engines for CI repair platform.

This module provides deterministic safety gates around autonomous CI/CD/CT
control actions. It enforces the platform's fail-closed principle: when
in doubt, block or escalate rather than allowing unsafe autonomous actions.

Module responsibility:
    - Evaluate policy contexts for delivery-state decisions
    - Apply deterministic safety gates for CI/CD actions
    - Provide final release boundary for tournament-selected repairs

Key invariants:
    - All decisions are deterministic given the same inputs
    - Fail-closed: unknown or unsafe conditions trigger BLOCK or ESCALATE
    - Retry budgets are tracked and enforced

Safety boundaries:
    - PolicyEngine checks conditions in priority order (highest risk first)
    - DefaultRepairPolicy uses fail-closed semantics for release decisions
    - RepairPolicyGate is the final boundary before canary/SLO gates

Failure modes:
    - PolicyEngine returns ESCALATE for low confidence (< 0.60)
    - PolicyEngine returns BLOCK for non-retryable, high-severity, or regression
    - DefaultRepairPolicy returns BLOCK if regression_free is False

Audit Notes:
    - All policy decisions include action, reason, confidence, and evidence
    - Policy decisions are machine-readable and auditable
    - Retry budgets are explicitly tracked and surfaced
"""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .control_plane import Decision, Evaluation, RunState
from .tournament import CandidateScore, TournamentResult


class Action(str, Enum):
    """Actions that can be returned by policy decisions.

    Values:
        PASS: Allow the operation to proceed
        RETRY: Allow retry within budget
        BLOCK: Block the operation (fail-closed)
        ESCALATE: Escalate to human review
        ROLLBACK: Trigger rollback of previous operation
    """

    PASS = "PASS"
    RETRY = "RETRY"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"
    ROLLBACK = "ROLLBACK"


@dataclass(frozen=True)
class DeliveryDecision:
    """Policy decision for delivery-state CI/CD/CT control actions.

    Captures the complete decision including the action, reasoning,
    confidence level, supporting evidence, and budget information.

    Attributes:
        action: The action to take (PASS, RETRY, BLOCK, ESCALATE, ROLLBACK)
        reason: Human-readable explanation for the decision
        confidence: Confidence level in the decision (0.0-1.0)
        evidence: Tuple of evidence tags supporting the decision
        policy_id: Identifier for the policy that produced this decision
        retry_budget_remaining: Remaining retry budget after this decision
    """

    action: Action
    reason: str
    confidence: float
    evidence: tuple[str, ...] = ()
    policy_id: str = "default-v1"
    retry_budget_remaining: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable dictionary representation.

        Returns:
            Dictionary with all decision fields, including action.value
        """
        data = asdict(self)
        data["action"] = self.action.value
        return data


@dataclass(frozen=True)
class PolicyContext:
    """Context for policy decision evaluation.

    Contains all the information needed to make a policy decision
    about a specific failure or repair attempt.

    Attributes:
        failure_class: Classification of the failure (e.g., "BUILD_ERROR", "TEST_ASSERTION")
        confidence: Diagnosis confidence level (0.0-1.0)
        retryable: Whether this failure type is retryable
        retry_count: Number of retries already attempted
        retry_budget: Maximum allowed retries
        repeated_signature: Number of times this exact failure signature has occurred
        ct_regression: Whether continuous testing detected a regression
        security_severity: Security severity level (e.g., "high", "critical"), or None
        canary_regression: Whether canary deployment detected a regression
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

    Evaluates PolicyContext and returns a DeliveryDecision based on
    a fixed priority order of safety checks. The engine enforces
    fail-closed semantics: any unsafe condition results in BLOCK
    or ROLLBACK, and uncertain conditions result in ESCALATE.

    Responsibility:
        - Evaluate safety conditions in priority order
        - Return deterministic decisions based on context
        - Track and surface remaining retry budget

    Priority order (highest to lowest):
        1. Canary regression -> ROLLBACK
        2. CT regression -> BLOCK
        3. High/critical security -> BLOCK
        4. Low confidence (< 0.60) -> ESCALATE
        5. Non-retryable failure -> BLOCK
        6. Retry budget exhausted -> ESCALATE
        7. Otherwise -> RETRY

    Usage:
        engine = PolicyEngine()
        decision = engine.decide(ctx)

    Side effects:
        None. decide() is a pure function from inputs.

    Audit Notes:
        - All decisions are deterministic given the same context
        - Fail-closed: BLOCK and ROLLBACK take precedence
        - Retry budget is computed and surfaced in the decision
    """

    def decide(self, ctx: PolicyContext) -> DeliveryDecision:
        """Evaluate context and return a delivery decision.

        Args:
            ctx: PolicyContext containing all decision inputs

        Returns:
            DeliveryDecision with action, reason, confidence, evidence, and budget

        Side effects:
            None.

        Audit Notes:
            - Conditions are checked in priority order (highest risk first)
            - Each decision includes specific evidence tags
            - retry_budget_remaining is computed as max(retry_budget - retry_count, 0)
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

    Makes release decisions based on evaluation results and run state.
    Enforces the safety invariant that regressions block release and
    that low-confidence repairs escalate rather than release.

    Responsibility:
        - Decide whether to release, retry, or escalate based on evaluation

    Invariants:
        - Regression detection blocks release (BLOCK)
        - Release requires both passed=True and score >= release_score
        - Retry requires score >= retry_score
        - Otherwise escalate

    Usage:
        policy = DefaultRepairPolicy(release_score=0.90, retry_score=0.60)
        decision = policy.decide(evaluation, state)

    Side effects:
        None. decide() is a pure function from inputs.

    Audit Notes:
        - regression_free=False always returns BLOCK
        - Release threshold is typically higher than retry threshold
    """

    def __init__(self, *, release_score: float = 0.90, retry_score: float = 0.60) -> None:
        """Initialize with score thresholds.

        Args:
            release_score: Minimum score for RELEASE decision
            retry_score: Minimum score for RETRY decision
        """
        self.release_score = release_score
        self.retry_score = retry_score

    def decide(self, evaluation: Evaluation, state: RunState) -> Decision:
        """Decide release action based on evaluation and state.

        Args:
            evaluation: Evaluation result from independent verification
            state: RunState from control plane

        Returns:
            Decision.RELEASE, RETRY, ESCALATE, or BLOCK

        Side effects:
            None.

        Audit Notes:
            - Regression detection takes highest priority (BLOCK)
            - Release requires both passed and high score
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
    """Final policy decision for tournament-selected repairs.

    Captures the action, reason, and whether human approval is required.

    Attributes:
        action: Action string (e.g., "ESCALATE_HUMAN", "READY_FOR_CANARY", "BLOCK")
        reason: Human-readable explanation for the decision
        requires_human_approval: Whether human approval is required to proceed
    """

    action: str
    reason: str
    requires_human_approval: bool


class RepairPolicyGate:
    """Final release boundary for tournament-selected, independently evaluated repairs.

    This is the last automated gate before canary deployment. It enforces
    budget limits on risk, cost, and latency, and ensures that only
    independently evaluated and accepted repairs can proceed.

    Responsibility:
        - Validate tournament winner against policy budgets
        - Ensure independent evaluation is present and successful
        - Return final policy decision for the repair

    Invariants:
        - Missing or unaccepted winner triggers human escalation
        - Budget violations trigger human approval requirement
        - Failed independent evaluation triggers BLOCK

    Usage:
        gate = RepairPolicyGate(max_risk_score=0.6, max_cost_usd=0.50)
        decision = gate.decide(tournament_result)

    Side effects:
        None. decide() is a pure function from inputs.

    Audit Notes:
        - This is the final automated gate before canary
        - Human approval requirement is surfaced explicitly
        - All budget checks are inclusive (value must be <= max)
    """

    def __init__(
        self,
        *,
        max_risk_score: float = 0.6,
        max_cost_usd: float = 0.50,
        max_latency_ms: int = 60_000,
    ) -> None:
        """Initialize with budget thresholds.

        Args:
            max_risk_score: Maximum acceptable risk score (0.0-1.0)
            max_cost_usd: Maximum acceptable cost in USD
            max_latency_ms: Maximum acceptable latency in milliseconds
        """
        self.max_risk_score = max_risk_score
        self.max_cost_usd = max_cost_usd
        self.max_latency_ms = max_latency_ms

    def decide(self, result: TournamentResult) -> PolicyDecision:
        """Evaluate tournament result against policy budgets.

        Args:
            result: TournamentResult with winner and other candidates

        Returns:
            PolicyDecision with action, reason, and human approval flag

        Side effects:
            None.

        Audit Notes:
            - Checks winner existence, acceptance, and action state first
            - Then checks budget constraints
            - Finally checks independent evaluation success
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
        """Check if candidate is within all budget constraints.

        Args:
            candidate: CandidateScore to check

        Returns:
            True if candidate is within all budgets, False otherwise

        Side effects:
            None.
        """
        return (
            0 <= candidate.risk_score <= self.max_risk_score
            and 0 <= candidate.cost_usd <= self.max_cost_usd
            and 0 <= candidate.latency_ms <= self.max_latency_ms
        )

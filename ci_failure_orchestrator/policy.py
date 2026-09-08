from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .control_plane import Decision, Evaluation, RunState
from .tournament import CandidateScore, TournamentResult


class Action(str, Enum):
    PASS = "PASS"
    RETRY = "RETRY"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"
    ROLLBACK = "ROLLBACK"


@dataclass(frozen=True)
class DeliveryDecision:
    """Policy decision for delivery-state CI/CD/CT control actions."""

    action: Action
    reason: str
    confidence: float
    evidence: tuple[str, ...] = ()
    policy_id: str = "default-v1"
    retry_budget_remaining: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        return data


@dataclass(frozen=True)
class PolicyContext:
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
    """Deterministic safety gate around autonomous CI/CD actions."""

    def decide(self, ctx: PolicyContext) -> DeliveryDecision:
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
    """Fail-closed release policy for the bounded autonomous control plane."""

    def __init__(self, *, release_score: float = 0.90, retry_score: float = 0.60) -> None:
        self.release_score = release_score
        self.retry_score = retry_score

    def decide(self, evaluation: Evaluation, state: RunState) -> Decision:
        if not evaluation.regression_free:
            return Decision.BLOCK
        if evaluation.passed and evaluation.score >= self.release_score:
            return Decision.RELEASE
        if evaluation.score >= self.retry_score:
            return Decision.RETRY
        return Decision.ESCALATE


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    reason: str
    requires_human_approval: bool


class RepairPolicyGate:
    """Final release boundary for tournament-selected, independently evaluated repairs."""

    def __init__(
        self,
        *,
        max_risk_score: float = 0.6,
        max_cost_usd: float = 0.50,
        max_latency_ms: int = 60_000,
    ) -> None:
        self.max_risk_score = max_risk_score
        self.max_cost_usd = max_cost_usd
        self.max_latency_ms = max_latency_ms

    def decide(self, result: TournamentResult) -> PolicyDecision:
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
        return (
            0 <= candidate.risk_score <= self.max_risk_score
            and 0 <= candidate.cost_usd <= self.max_cost_usd
            and 0 <= candidate.latency_ms <= self.max_latency_ms
        )

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class Action(str, Enum):
    PASS = "PASS"
    RETRY = "RETRY"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"
    ROLLBACK = "ROLLBACK"


@dataclass(frozen=True)
class Decision:
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

    def decide(self, ctx: PolicyContext) -> Decision:
        remaining = max(ctx.retry_budget - ctx.retry_count, 0)
        if ctx.canary_regression:
            return Decision(Action.ROLLBACK, "canary regression detected", 1.0, ("canary_regression",), retry_budget_remaining=remaining)
        if ctx.ct_regression:
            return Decision(Action.BLOCK, "continuous-testing regression detected", 1.0, ("ct_regression",), retry_budget_remaining=remaining)
        if (ctx.security_severity or "").lower() in {"high", "critical"}:
            return Decision(Action.BLOCK, "high-severity security failure", 1.0, (f"security:{ctx.security_severity}",), retry_budget_remaining=remaining)
        if ctx.confidence < 0.60:
            return Decision(Action.ESCALATE, "diagnosis confidence below policy threshold", ctx.confidence, ("low_confidence",), retry_budget_remaining=remaining)
        if not ctx.retryable:
            return Decision(Action.BLOCK, "deterministic/non-retryable failure", ctx.confidence, (ctx.failure_class,), retry_budget_remaining=remaining)
        if ctx.retry_count >= ctx.retry_budget or ctx.repeated_signature >= 2:
            return Decision(Action.ESCALATE, "retry/stopping condition reached", ctx.confidence, ("retry_budget",), retry_budget_remaining=remaining)
        return Decision(Action.RETRY, "failure is retryable within budget", ctx.confidence, (ctx.failure_class,), retry_budget_remaining=remaining)

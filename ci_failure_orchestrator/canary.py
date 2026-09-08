from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable


@dataclass(frozen=True)
class CanaryResult:
    deployed: bool
    healthy: bool
    rolled_back: bool
    reason: str


class CanaryController:
    """Small execution boundary for canary deploy/health/rollback hooks."""

    def __init__(
        self,
        deploy: Callable[[], bool],
        health_check: Callable[[], bool],
        rollback: Callable[[], bool],
    ):
        self.deploy = deploy
        self.health_check = health_check
        self.rollback = rollback

    def run(self) -> CanaryResult:
        if not self.deploy():
            return CanaryResult(False, False, False, "canary deployment failed")
        if self.health_check():
            return CanaryResult(True, True, False, "canary healthy")
        rolled_back = self.rollback()
        return CanaryResult(
            True,
            False,
            rolled_back,
            "canary unhealthy; rollback executed" if rolled_back else "canary unhealthy; rollback failed",
        )


class CanaryDecision(str, Enum):
    PROMOTE = "promote"
    HOLD = "hold"
    ROLLBACK = "rollback"


@dataclass(frozen=True)
class CanaryMetrics:
    sample_size: int
    success_rate: float
    regression_rate: float
    false_repair_rate: float
    p95_latency_ms: int


@dataclass(frozen=True)
class CanaryPolicy:
    min_sample_size: int = 10
    min_success_rate: float = 0.90
    max_regression_rate: float = 0.01
    max_false_repair_rate: float = 0.02
    max_p95_latency_ms: int = 300_000


def evaluate_canary(metrics: CanaryMetrics, policy: CanaryPolicy = CanaryPolicy()) -> CanaryDecision:
    if metrics.regression_rate > policy.max_regression_rate:
        return CanaryDecision.ROLLBACK
    if metrics.false_repair_rate > policy.max_false_repair_rate:
        return CanaryDecision.ROLLBACK
    if metrics.sample_size < policy.min_sample_size:
        return CanaryDecision.HOLD
    if metrics.success_rate < policy.min_success_rate:
        return CanaryDecision.HOLD
    if metrics.p95_latency_ms > policy.max_p95_latency_ms:
        return CanaryDecision.HOLD
    return CanaryDecision.PROMOTE

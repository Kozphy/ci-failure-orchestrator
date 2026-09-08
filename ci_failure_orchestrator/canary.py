from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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

"""Telemetry aggregation for autonomous CI repair effectiveness."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Iterable


@dataclass(frozen=True)
class RepairObservation:
    """One completed repair attempt used for effectiveness metrics."""

    provider: str
    worker: str
    success: bool
    false_repair: bool
    cost_usd: float
    latency_ms: int
    attempts: int = 1


@dataclass(frozen=True)
class RepairMetrics:
    """Aggregate metrics for one provider or worker population."""

    total: int
    successes: int
    false_repairs: int
    success_rate: float
    false_repair_rate: float
    mean_cost_usd: float
    cost_per_success_usd: float | None
    mean_latency_ms: float
    p95_latency_ms: int
    mean_attempts: float


def _p95(values: list[int]) -> int:
    """Return nearest-rank P95 for a non-empty integer sample."""

    ordered = sorted(values)
    rank = max(1, int((0.95 * len(ordered)) + 0.999999))
    return ordered[min(rank - 1, len(ordered) - 1)]


def aggregate_metrics(observations: Iterable[RepairObservation]) -> RepairMetrics:
    """Aggregate measurable repair quality, cost, and latency outcomes."""

    rows = tuple(observations)
    if not rows:
        return RepairMetrics(0, 0, 0, 0.0, 0.0, 0.0, None, 0.0, 0, 0.0)

    successes = sum(row.success for row in rows)
    false_repairs = sum(row.false_repair for row in rows)
    total_cost = sum(row.cost_usd for row in rows)
    latencies = [row.latency_ms for row in rows]
    return RepairMetrics(
        total=len(rows),
        successes=successes,
        false_repairs=false_repairs,
        success_rate=successes / len(rows),
        false_repair_rate=false_repairs / len(rows),
        mean_cost_usd=mean(row.cost_usd for row in rows),
        cost_per_success_usd=(total_cost / successes) if successes else None,
        mean_latency_ms=mean(latencies),
        p95_latency_ms=_p95(latencies),
        mean_attempts=mean(row.attempts for row in rows),
    )


def group_metrics_by_provider(
    observations: Iterable[RepairObservation],
) -> dict[str, RepairMetrics]:
    """Aggregate effectiveness metrics independently for each provider."""

    groups: dict[str, list[RepairObservation]] = {}
    for observation in observations:
        groups.setdefault(observation.provider, []).append(observation)
    return {provider: aggregate_metrics(rows) for provider, rows in groups.items()}

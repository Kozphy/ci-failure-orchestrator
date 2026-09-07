"""Replayable benchmark primitives for CI repair systems."""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import Iterable


@dataclass(frozen=True)
class BenchmarkResult:
    case_id: str
    root_stage_correct: bool
    repaired: bool
    regression: bool
    escalated: bool
    retries: int
    cost: float
    latency_ms: float
    root_cause_top3: bool | None = None
    false_repair: bool | None = None


@dataclass(frozen=True)
class BenchmarkSummary:
    cases: int
    root_cause_accuracy: float
    repair_success_rate: float
    false_repair_rate: float
    regression_rate: float
    escalation_rate: float
    mean_retries: float
    mean_cost: float
    p50_latency_ms: float
    top3_root_cause_accuracy: float = 0.0
    p95_latency_ms: float = 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


class BenchmarkSuite:
    @staticmethod
    def summarize(results: Iterable[BenchmarkResult]) -> BenchmarkSummary:
        rows = list(results)
        if not rows:
            raise ValueError("benchmark requires at least one result")
        n = len(rows)
        successful = [r for r in rows if r.repaired]
        false_repairs = [
            r
            for r in successful
            if (r.false_repair if r.false_repair is not None else r.regression)
        ]
        top3_hits = [
            r.root_cause_top3 if r.root_cause_top3 is not None else r.root_stage_correct
            for r in rows
        ]
        latencies = [r.latency_ms for r in rows]
        return BenchmarkSummary(
            cases=n,
            root_cause_accuracy=sum(r.root_stage_correct for r in rows) / n,
            repair_success_rate=len(successful) / n,
            false_repair_rate=(len(false_repairs) / len(successful)) if successful else 0.0,
            regression_rate=sum(r.regression for r in rows) / n,
            escalation_rate=sum(r.escalated for r in rows) / n,
            mean_retries=mean(r.retries for r in rows),
            mean_cost=mean(r.cost for r in rows),
            p50_latency_ms=median(latencies),
            top3_root_cause_accuracy=sum(top3_hits) / n,
            p95_latency_ms=_percentile(latencies, 0.95),
        )

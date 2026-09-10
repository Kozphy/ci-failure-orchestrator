"""Replayable benchmark primitives for CI repair systems.

This module provides data structures and aggregation functions for benchmarking
CI repair operations, including metrics for root-cause accuracy, repair success
rate, false repair rate, regression rate, escalation rate, cost, and latency.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import Iterable


@dataclass(frozen=True)
class BenchmarkResult:
    """Result from a single benchmark case execution.

    Attributes:
        case_id: Unique identifier for the benchmark case.
        root_stage_correct: Whether the root-cause stage was correctly identified.
        repaired: Whether the repair was successful.
        regression: Whether the repair introduced a regression.
        escalated: Whether the case was escalated to human review.
        retries: Number of retry attempts.
        cost: Total cost of the repair operation.
        latency_ms: Total latency in milliseconds.
        root_cause_top3: Whether root cause was in top-3 predictions (optional).
        false_repair: Whether the repair was a false positive (optional).
    """

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
    """Aggregated metrics from multiple benchmark results.

    Attributes:
        cases: Total number of benchmark cases.
        root_cause_accuracy: Proportion of cases with correct root-cause stage.
        repair_success_rate: Proportion of cases where repair succeeded.
        false_repair_rate: Proportion of successful repairs that were false positives.
        regression_rate: Proportion of cases that introduced regressions.
        escalation_rate: Proportion of cases that required escalation.
        mean_retries: Average number of retry attempts.
        mean_cost: Average cost per repair operation.
        p50_latency_ms: Median latency in milliseconds.
        top3_root_cause_accuracy: Proportion with root cause in top-3 predictions.
        p95_latency_ms: 95th percentile latency in milliseconds.
    """

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
    """Calculate the approximate percentile value from a list.

    Args:
        values: List of numeric values.
        percentile: Percentile to calculate (0.0 to 1.0).

    Returns:
        Approximate percentile value, or 0.0 if the list is empty.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


class BenchmarkSuite:
    """Aggregates benchmark results into production-facing metrics.

    This class provides static methods for summarizing benchmark results into
    aggregated metrics that can be used for SLO evaluation, dashboard visualization,
    and performance tracking.
    """

    @staticmethod
    def summarize(results: Iterable[BenchmarkResult]) -> BenchmarkSummary:
        """Summarize benchmark results into aggregated metrics.

        Args:
            results: Iterable of benchmark results to summarize.

        Returns:
            BenchmarkSummary with aggregated metrics across all results.

        Raises:
            ValueError: If no results are provided.

        Metrics Calculated:
            - root_cause_accuracy: Proportion of correct root-cause identifications.
            - repair_success_rate: Proportion of successful repairs.
            - false_repair_rate: Proportion of false positives among successful repairs.
            - regression_rate: Proportion of repairs that introduced regressions.
            - escalation_rate: Proportion of cases requiring human escalation.
            - mean_retries: Average retry attempts per case.
            - mean_cost: Average cost per repair operation.
            - p50_latency_ms: Median repair latency.
            - top3_root_cause_accuracy: Proportion with root cause in top-3 predictions.
            - p95_latency_ms: 95th percentile repair latency.
        """
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

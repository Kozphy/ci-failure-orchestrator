"""Replayable benchmark primitives for CI repair systems.

This module provides data structures and computation for aggregating
repair case results into production-facing metrics. It supports the
platform's requirement for evidence-backed quality measurement.

Module responsibility:
    - Define benchmark result data structure
    - Aggregate results into summary metrics
    - Compute percentile statistics for latency analysis

Key invariants:
    - BenchmarkSummary is computed from one or more BenchmarkResult instances
    - Percentile computation uses linear interpolation via sorted index
    - Empty results raise ValueError (fail-fast on invalid input)

Safety boundaries:
    - summarize() requires at least one result; empty input is an error
    - All computations are deterministic given the same inputs
    - Division by zero is protected for edge cases

Audit Notes:
    - BenchmarkSummary metrics are used for platform dashboard and evidence
    - false_repair_rate is computed only from successful repairs
    - Percentile values are computed from sorted latency observations
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import Iterable


@dataclass(frozen=True)
class BenchmarkResult:
    """Result of a single benchmark case execution.

    Captures all metrics and outcomes for one repair attempt.

    Attributes:
        case_id: Unique identifier for this benchmark case
        root_stage_correct: Whether the identified root stage was correct
        repaired: Whether the repair attempt succeeded
        regression: Whether the repair introduced a regression
        escalated: Whether the case was escalated to human review
        retries: Number of repair attempts made
        cost: Cost of repair in currency units (e.g., USD)
        latency_ms: Repair latency in milliseconds
        root_cause_top3: Whether root cause was in top-3 ranked failures (optional)
        false_repair: Whether the repair was a false repair (optional)
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
    """Aggregated metrics across all benchmark cases.

    Provides production-facing quality signals derived from benchmark results.

    Attributes:
        cases: Total number of benchmark cases
        root_cause_accuracy: Fraction of cases where root stage was correctly identified
        repair_success_rate: Fraction of cases that were successfully repaired
        false_repair_rate: Fraction of successful repairs that were false repairs
        regression_rate: Fraction of cases that introduced regressions
        escalation_rate: Fraction of cases that were escalated
        mean_retries: Average number of retries per case
        mean_cost: Average cost per case
        p50_latency_ms: Median (50th percentile) latency in milliseconds
        top3_root_cause_accuracy: Fraction where root cause was in top-3 (default 0.0)
        p95_latency_ms: 95th percentile latency in milliseconds (default 0.0)
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
    """Compute percentile from a list of values.

    Uses linear interpolation via sorted index selection.

    Args:
        values: List of numeric values
        percentile: Percentile to compute (0.0-1.0)

    Returns:
        The value at the computed percentile index, or 0.0 if values is empty
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


class BenchmarkSuite:
    """Aggregator for benchmark results.

    Provides static methods for summarizing collections of BenchmarkResult
    instances into BenchmarkSummary metrics.

    Responsibility:
        - Aggregate benchmark results into summary metrics
        - Compute derived statistics (percentiles, averages)

    Usage:
        summary = BenchmarkSuite.summarize([result1, result2, ...])

    Side effects:
        None. summarize() is a pure function.

    Audit Notes:
        - summarize() raises ValueError on empty input
        - All statistics are computed from the provided results only
    """

    @staticmethod
    def summarize(results: Iterable[BenchmarkResult]) -> BenchmarkSummary:
        """Aggregate benchmark results into a summary.

        Computes all production-facing metrics from the provided results.
        Raises ValueError if no results are provided (fail-fast).

        Args:
            results: Iterable of BenchmarkResult instances

        Returns:
            BenchmarkSummary with all aggregated metrics

        Raises:
            ValueError: If results is empty

        Side effects:
            None. Pure computation from inputs.

        Audit Notes:
            - false_repair is inferred from regression when not explicitly provided
            - false_repair_rate is 0.0 if no repairs succeeded (avoids division by zero)
            - Percentile computations use the internal _percentile helper
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

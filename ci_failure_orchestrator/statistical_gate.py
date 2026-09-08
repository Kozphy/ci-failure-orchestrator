"""Confidence-aware promotion gates for benchmark evidence."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable

from .benchmark_suite import BenchmarkResult


@dataclass(frozen=True)
class WilsonInterval:
    """Binomial proportion interval bounded to [0, 1]."""

    estimate: float
    lower: float
    upper: float


@dataclass(frozen=True)
class StatisticalGatePolicy:
    """Evidence requirements before autonomous repair may be promoted."""

    min_cases: int = 50
    min_repair_success_rate: float = 0.90
    max_regression_rate: float = 0.02
    max_false_repair_rate: float = 0.02
    z_score: float = 1.959963984540054


@dataclass(frozen=True)
class StatisticalGateResult:
    """Decision and confidence evidence produced by the statistical gate."""

    passed: bool
    cases: int
    checks: dict[str, bool]
    repair_success: WilsonInterval
    regression: WilsonInterval
    false_repair: WilsonInterval

    @property
    def decision(self) -> str:
        return "PASS" if self.passed else "BLOCK"

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "decision": self.decision,
            "cases": self.cases,
            "checks": self.checks,
            "repair_success": self.repair_success.__dict__,
            "regression": self.regression.__dict__,
            "false_repair": self.false_repair.__dict__,
        }


def wilson_interval(successes: int, trials: int, *, z_score: float = 1.959963984540054) -> WilsonInterval:
    """Return a Wilson score interval for a binomial proportion."""
    if trials <= 0:
        return WilsonInterval(0.0, 0.0, 1.0)
    if successes < 0 or successes > trials:
        raise ValueError("successes must be between zero and trials")
    if z_score <= 0:
        raise ValueError("z_score must be positive")

    p_hat = successes / trials
    z2 = z_score * z_score
    denominator = 1.0 + z2 / trials
    centre = (p_hat + z2 / (2.0 * trials)) / denominator
    radius = (
        z_score
        * sqrt((p_hat * (1.0 - p_hat) / trials) + (z2 / (4.0 * trials * trials)))
        / denominator
    )
    return WilsonInterval(
        estimate=p_hat,
        lower=max(0.0, centre - radius),
        upper=min(1.0, centre + radius),
    )


def evaluate_statistical_gate(
    results: Iterable[BenchmarkResult],
    policy: StatisticalGatePolicy | None = None,
) -> StatisticalGateResult:
    """Fail closed unless benchmark evidence clears confidence-aware thresholds.

    Success uses a lower confidence bound: even the pessimistic estimate must meet
    the required repair rate. Regression and false-repair use upper confidence
    bounds: even the pessimistic risk estimate must remain below policy limits.
    """
    policy = policy or StatisticalGatePolicy()
    rows = list(results)
    n = len(rows)

    repaired = sum(row.repaired for row in rows)
    regressions = sum(row.regression for row in rows)
    false_repairs = sum(
        bool(row.false_repair if row.false_repair is not None else row.regression)
        for row in rows
    )

    repair_interval = wilson_interval(repaired, n, z_score=policy.z_score)
    regression_interval = wilson_interval(regressions, n, z_score=policy.z_score)
    false_repair_interval = wilson_interval(false_repairs, n, z_score=policy.z_score)

    checks = {
        "minimum_sample_size": n >= policy.min_cases,
        "repair_success_lower_bound": repair_interval.lower >= policy.min_repair_success_rate,
        "regression_upper_bound": regression_interval.upper <= policy.max_regression_rate,
        "false_repair_upper_bound": false_repair_interval.upper <= policy.max_false_repair_rate,
    }
    return StatisticalGateResult(
        passed=all(checks.values()),
        cases=n,
        checks=checks,
        repair_success=repair_interval,
        regression=regression_interval,
        false_repair=false_repair_interval,
    )

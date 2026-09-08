"""Small dependency-free statistics helpers for research-grade benchmark reports."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt


@dataclass(frozen=True)
class ProportionEstimate:
    """Observed binary rate with a Wilson 95% confidence interval."""

    successes: int
    total: int
    rate: float
    ci95_low: float
    ci95_high: float

    def to_dict(self) -> dict:
        """Return a JSON-serializable representation."""
        return asdict(self)


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> ProportionEstimate:
    """Estimate a binomial proportion and Wilson confidence interval.

    Wilson intervals remain well behaved near 0 and 1 and avoid adding a
    heavyweight statistics dependency to the benchmark runner.
    """
    if total <= 0:
        raise ValueError("total must be positive")
    if successes < 0 or successes > total:
        raise ValueError("successes must be between 0 and total")
    p = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = (p + z2 / (2.0 * total)) / denominator
    margin = z * sqrt((p * (1.0 - p) / total) + z2 / (4.0 * total * total)) / denominator
    # Closed-form Wilson endpoints are exact at 0 and 1 successes-total, but
    # floating-point arithmetic can leave a ULP inside the bound.
    low = 0.0 if successes == 0 else max(0.0, centre - margin)
    high = 1.0 if successes == total else min(1.0, centre + margin)
    return ProportionEstimate(successes, total, p, low, high)


@dataclass(frozen=True)
class PairedBinaryComparison:
    """Case-level comparison between two systems evaluated on identical cases."""

    cases: int
    a_wins: int
    b_wins: int
    ties: int
    absolute_rate_delta: float

    def to_dict(self) -> dict:
        """Return a JSON-serializable representation."""
        return asdict(self)


def compare_paired_binary(a: list[bool], b: list[bool]) -> PairedBinaryComparison:
    """Compare paired binary outcomes without pretending they are independent."""
    if len(a) != len(b):
        raise ValueError("paired outcomes must have equal length")
    if not a:
        raise ValueError("paired comparison requires at least one case")
    a_wins = sum(left and not right for left, right in zip(a, b))
    b_wins = sum(right and not left for left, right in zip(a, b))
    ties = len(a) - a_wins - b_wins
    return PairedBinaryComparison(
        cases=len(a),
        a_wins=a_wins,
        b_wins=b_wins,
        ties=ties,
        absolute_rate_delta=(sum(a) - sum(b)) / len(a),
    )

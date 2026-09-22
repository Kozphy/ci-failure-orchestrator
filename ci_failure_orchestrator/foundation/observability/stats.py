"""Deterministic distribution summaries (no heavy stats libs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class DistributionSummary:
    count: int
    min: float | None
    median: float | None
    p95: float | None
    max: float | None

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "count": self.count,
            "min": self.min,
            "median": self.median,
            "p95": self.p95,
            "max": self.max,
        }


def percentile(sorted_values: Sequence[float], p: float) -> float | None:
    """Nearest-rank percentile on a pre-sorted ascending sequence.

    Method: index = ceil(p/100 * N) - 1, clamped to [0, N-1].
    Documented for Phase 13 reports/tests — do not change without updating docs.
    """

    if not sorted_values:
        return None
    if p <= 0:
        return float(sorted_values[0])
    if p >= 100:
        return float(sorted_values[-1])
    n = len(sorted_values)
    # nearest-rank: rank = ceil(p/100 * n)
    rank = int(-(-((p / 100.0) * n) // 1))  # ceil without math import
    idx = max(0, min(n - 1, rank - 1))
    return float(sorted_values[idx])


def summarize_distribution(values: Sequence[float]) -> DistributionSummary:
    if not values:
        return DistributionSummary(0, None, None, None, None)
    ordered = sorted(float(v) for v in values)
    return DistributionSummary(
        count=len(ordered),
        min=ordered[0],
        median=percentile(ordered, 50),
        p95=percentile(ordered, 95),
        max=ordered[-1],
    )

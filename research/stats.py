"""Uncertainty and paired comparisons, stdlib only and seeded.

* Wilson score interval for a single proportion (well behaved at small n and at 0 or 1).
* Percentile bootstrap over cases for any per-case statistic.
* Paired bootstrap of the difference between two systems evaluated on the same cases.
* Exact McNemar test (two-sided binomial on discordant pairs) for paired binary outcomes.

Assumptions: cases are treated as exchangeable draws from the case population the dataset represents.
The authored synthetic cases are not a random sample of real CI failures, so intervals describe
sampling variability over cases like these, not uncertainty about production behaviour.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from typing import Any

DEFAULT_RESAMPLES = 2000
Z_95 = 1.959963984540054


def wilson(successes: int, n: int, z: float = Z_95) -> dict[str, Any]:
    """Wilson score interval; ``None`` bounds with a reason when n is 0."""
    if n <= 0:
        return {"k": successes, "n": n, "estimate": None, "low": None, "high": None, "reason": "n=0"}
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {"k": successes, "n": n, "estimate": p, "low": max(0.0, centre - half), "high": min(1.0, centre + half)}


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("empty")
    pos = (len(sorted_values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def bootstrap(
    items: Sequence[Any],
    statistic: Callable[[Sequence[Any]], float | None],
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Percentile bootstrap CI of ``statistic`` over resampled cases."""
    estimate = statistic(items) if items else None
    if not items or estimate is None:
        return {"estimate": estimate, "low": None, "high": None, "n": len(items), "resamples": 0,
                "seed": seed, "reason": "no scorable cases"}
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        sample = [items[rng.randrange(len(items))] for _ in items]
        value = statistic(sample)
        if value is not None:
            values.append(value)
    values.sort()
    return {
        "estimate": estimate,
        "low": _percentile(values, alpha / 2),
        "high": _percentile(values, 1 - alpha / 2),
        "n": len(items),
        "resamples": len(values),
        "seed": seed,
        "method": "percentile bootstrap over cases",
    }


def mean_of(values: Sequence[float]) -> float | None:
    """Arithmetic mean; ``None`` for an empty sequence."""
    return sum(values) / len(values) if values else None


def paired_bootstrap(
    a: Sequence[float], b: Sequence[float], *, seed: int, resamples: int = DEFAULT_RESAMPLES, alpha: float = 0.05
) -> dict[str, Any]:
    """Bootstrap CI of mean(a - b) over paired cases, plus the share of resamples with a difference <= 0.

    The share is a descriptive bootstrap quantity, not a p-value.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    result = bootstrap(diffs, mean_of, seed=seed, resamples=resamples, alpha=alpha)
    if diffs:
        rng = random.Random(seed + 1)
        at_or_below = 0
        for _ in range(resamples):
            sample = [diffs[rng.randrange(len(diffs))] for _ in diffs]
            at_or_below += (sum(sample) / len(sample)) <= 0
        result["share_resamples_diff_le_0"] = at_or_below / resamples
    result["method"] = "paired percentile bootstrap of mean difference (a - b)"
    return result


def mcnemar_exact(a: Sequence[bool], b: Sequence[bool]) -> dict[str, Any]:
    """Exact two-sided McNemar test on paired binary outcomes.

    ``b01`` counts cases where a is False and b is True; ``b10`` the reverse.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    b01 = sum(1 for x, y in zip(a, b, strict=True) if not x and y)
    b10 = sum(1 for x, y in zip(a, b, strict=True) if x and not y)
    n = b01 + b10
    if n == 0:
        return {"b01": 0, "b10": 0, "discordant": 0, "p_value": None,
                "reason": "no discordant pairs; the test is undefined", "n_pairs": len(a)}
    k = min(b01, b10)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return {"b01": b01, "b10": b10, "discordant": n, "p_value": min(1.0, 2 * tail), "n_pairs": len(a),
            "method": "exact binomial McNemar, two-sided"}

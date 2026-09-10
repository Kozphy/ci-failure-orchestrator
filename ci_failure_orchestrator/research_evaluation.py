from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import random
from typing import Any, Iterable

from .corpus_benchmark import build_graph, failures_for_case
from .ranker import RootCauseRanker


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    truth: str
    proposed_prediction: str | None
    baseline_prediction: str | None
    proposed_correct: bool
    baseline_correct: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PairedResearchMetrics:
    cases: int
    proposed_accuracy: float
    baseline_accuracy: float
    absolute_uplift: float
    uplift_ci95_low: float
    uplift_ci95_high: float
    discordant_proposed_wins: int
    discordant_baseline_wins: int
    mcnemar_exact_p_value: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_case_outcomes(corpus: dict[str, Any]) -> list[CaseOutcome]:
    """Evaluate dependency-aware ranking against a deterministic latest-visible baseline."""
    graph = build_graph(corpus)
    ranker = RootCauseRanker(graph)
    outcomes: list[CaseOutcome] = []

    for case in corpus.get("cases", []):
        failures = failures_for_case(case)
        ranked = ranker.rank(failures)
        proposed = ranked[0].failure.stage if ranked else None
        baseline = (
            max(failures, key=lambda failure: graph.depth(failure.stage)).stage
            if failures
            else None
        )
        truth = str(case["root_cause"])
        outcomes.append(
            CaseOutcome(
                case_id=str(case["id"]),
                truth=truth,
                proposed_prediction=proposed,
                baseline_prediction=baseline,
                proposed_correct=proposed == truth,
                baseline_correct=baseline == truth,
            )
        )
    return outcomes


def _accuracy(items: Iterable[bool]) -> float:
    values = list(items)
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def bootstrap_paired_uplift_ci(
    outcomes: list[CaseOutcome], *, trials: int = 10_000, seed: int = 20260910
) -> tuple[float, float]:
    """Return a percentile bootstrap 95% CI for paired accuracy uplift."""
    if not outcomes:
        return 0.0, 0.0
    rng = random.Random(seed)
    n = len(outcomes)
    uplifts: list[float] = []
    for _ in range(trials):
        sample = [outcomes[rng.randrange(n)] for _ in range(n)]
        proposed = _accuracy(item.proposed_correct for item in sample)
        baseline = _accuracy(item.baseline_correct for item in sample)
        uplifts.append(proposed - baseline)
    return _percentile(uplifts, 0.025), _percentile(uplifts, 0.975)


def mcnemar_exact_p_value(proposed_wins: int, baseline_wins: int) -> float:
    """Two-sided exact McNemar/binomial p-value for discordant paired outcomes."""
    n = proposed_wins + baseline_wins
    if n == 0:
        return 1.0
    k = min(proposed_wins, baseline_wins)
    lower_tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2.0 * lower_tail)


def summarize_paired_outcomes(
    outcomes: list[CaseOutcome], *, bootstrap_trials: int = 10_000, seed: int = 20260910
) -> PairedResearchMetrics:
    proposed_accuracy = _accuracy(item.proposed_correct for item in outcomes)
    baseline_accuracy = _accuracy(item.baseline_correct for item in outcomes)
    proposed_wins = sum(
        item.proposed_correct and not item.baseline_correct for item in outcomes
    )
    baseline_wins = sum(
        item.baseline_correct and not item.proposed_correct for item in outcomes
    )
    low, high = bootstrap_paired_uplift_ci(
        outcomes, trials=bootstrap_trials, seed=seed
    )
    return PairedResearchMetrics(
        cases=len(outcomes),
        proposed_accuracy=round(proposed_accuracy, 4),
        baseline_accuracy=round(baseline_accuracy, 4),
        absolute_uplift=round(proposed_accuracy - baseline_accuracy, 4),
        uplift_ci95_low=round(low, 4),
        uplift_ci95_high=round(high, 4),
        discordant_proposed_wins=proposed_wins,
        discordant_baseline_wins=baseline_wins,
        mcnemar_exact_p_value=round(
            mcnemar_exact_p_value(proposed_wins, baseline_wins), 6
        ),
    )


def canonical_json_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

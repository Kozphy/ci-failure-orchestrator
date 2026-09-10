from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from .corpus_benchmark import build_graph, failures_for_case
from .ranker import RootCauseRanker


@dataclass(frozen=True)
class BaselinePrediction:
    case_id: str
    truth: str
    prediction: str | None
    correct: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def latest_visible_baseline(corpus: dict[str, Any]) -> list[BaselinePrediction]:
    """B0: predict the deepest/latest visible failed stage.

    This is a deterministic, dependency-agnostic operational heuristic used as a
    weak baseline. It does not call an LLM and does not use failure memory.
    """
    graph = build_graph(corpus)
    predictions: list[BaselinePrediction] = []
    for case in corpus.get("cases", []):
        failures = failures_for_case(case)
        prediction = (
            max(failures, key=lambda failure: graph.depth(failure.stage)).stage
            if failures
            else None
        )
        truth = str(case["root_cause"])
        predictions.append(
            BaselinePrediction(
                case_id=str(case["id"]),
                truth=truth,
                prediction=prediction,
                correct=prediction == truth,
            )
        )
    return predictions


def dependency_graph_baseline(corpus: dict[str, Any]) -> list[BaselinePrediction]:
    """B3: dependency-aware root-cause ranking without memory or LLM reasoning."""
    graph = build_graph(corpus)
    ranker = RootCauseRanker(graph)
    predictions: list[BaselinePrediction] = []
    for case in corpus.get("cases", []):
        failures = failures_for_case(case)
        ranked = ranker.rank(failures)
        prediction = ranked[0].failure.stage if ranked else None
        truth = str(case["root_cause"])
        predictions.append(
            BaselinePrediction(
                case_id=str(case["id"]),
                truth=truth,
                prediction=prediction,
                correct=prediction == truth,
            )
        )
    return predictions


BASELINE_RUNNERS: dict[str, Callable[[dict[str, Any]], list[BaselinePrediction]]] = {
    "B0": latest_visible_baseline,
    "B3": dependency_graph_baseline,
}


def run_baseline(baseline_id: str, corpus: dict[str, Any]) -> list[BaselinePrediction]:
    try:
        runner = BASELINE_RUNNERS[baseline_id]
    except KeyError as exc:
        supported = ", ".join(sorted(BASELINE_RUNNERS))
        raise ValueError(f"Unsupported executable baseline {baseline_id!r}; supported: {supported}") from exc
    return runner(corpus)

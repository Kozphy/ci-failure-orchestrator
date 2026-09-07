from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .graph import PipelineGraph
from .models import Failure, Stage
from .ranker import RootCauseRanker


@dataclass(frozen=True)
class CorpusMetrics:
    cases: int
    top1_accuracy: float
    top3_accuracy: float
    mean_cascade_elimination: float
    latest_visible_top1_accuracy: float
    causal_uplift_vs_latest_visible: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_graph(corpus: dict[str, Any]) -> PipelineGraph:
    stages = [
        Stage(
            id=item["id"],
            depends_on=tuple(item.get("depends_on", [])),
            criticality=float(item.get("criticality", 0.5)),
        )
        for item in corpus["stages"]
    ]
    return PipelineGraph(stages)


def failures_for_case(case: dict[str, Any]) -> list[Failure]:
    return [
        Failure(
            stage=item["stage"],
            error_type=item["error_type"],
            message=item.get("message", ""),
            severity=float(item.get("severity", 0.5)),
            confidence=float(item.get("confidence", 0.5)),
        )
        for item in case["failures"]
    ]


def evaluate_corpus(corpus: dict[str, Any]) -> CorpusMetrics:
    graph = build_graph(corpus)
    ranker = RootCauseRanker(graph)
    cases = corpus.get("cases", [])
    if not cases:
        return CorpusMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0)

    causal_top1 = 0
    causal_top3 = 0
    latest_top1 = 0
    cascade_scores: list[float] = []

    for case in cases:
        failures = failures_for_case(case)
        ranked = ranker.rank(failures)
        ranked_stages = [item.failure.stage for item in ranked]
        truth = case["root_cause"]
        causal_top1 += bool(ranked_stages and ranked_stages[0] == truth)
        causal_top3 += truth in ranked_stages[:3]

        latest_visible = max(failures, key=lambda failure: graph.depth(failure.stage))
        latest_top1 += latest_visible.stage == truth

        before = set(case.get("failed_before", []))
        after = set(case.get("failed_after_fix", []))
        downstream = before - {truth}
        cascade_scores.append(
            (len(downstream - after) / len(downstream)) if downstream else 1.0
        )

    count = len(cases)
    causal_accuracy = causal_top1 / count
    latest_accuracy = latest_top1 / count
    return CorpusMetrics(
        cases=count,
        top1_accuracy=round(causal_accuracy, 4),
        top3_accuracy=round(causal_top3 / count, 4),
        mean_cascade_elimination=round(sum(cascade_scores) / count, 4),
        latest_visible_top1_accuracy=round(latest_accuracy, 4),
        causal_uplift_vs_latest_visible=round(causal_accuracy - latest_accuracy, 4),
    )

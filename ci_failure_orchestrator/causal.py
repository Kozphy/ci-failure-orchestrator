from __future__ import annotations
from dataclasses import dataclass, asdict
from .graph import PipelineGraph
from .models import Failure
from .ranker import CAUSE_RULES

@dataclass(frozen=True)
class CausalEdge:
    source: str
    target: str
    confidence: float
    evidence: tuple[str, ...]

    def to_dict(self):
        return asdict(self)


def infer_causal_edges(graph: PipelineGraph, failures: list[Failure]) -> list[CausalEdge]:
    by_stage = {failure.stage: failure for failure in failures}
    edges: list[CausalEdge] = []
    for source in failures:
        for target_stage in graph.descendants(source.stage):
            target = by_stage.get(target_stage)
            if target is None:
                continue
            evidence: list[str] = []
            score = 0.0
            if target.error_type in CAUSE_RULES.get(source.error_type, set()):
                evidence.append("error-type causal rule")
                score += 0.45
            distance = max(graph.depth(target.stage) - graph.depth(source.stage), 1)
            evidence.append(f"pipeline upstream distance={distance}")
            score += 0.30 / distance
            score += 0.25 * source.confidence
            if score >= 0.45:
                edges.append(CausalEdge(source.stage, target.stage, round(min(score, 1.0), 4), tuple(evidence)))
    return sorted(edges, key=lambda edge: (edge.source, edge.target))

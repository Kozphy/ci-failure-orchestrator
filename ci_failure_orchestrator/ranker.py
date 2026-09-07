from __future__ import annotations

from .graph import PipelineGraph
from .models import Failure, RankedFailure


CAUSE_RULES: dict[str, set[str]] = {
    "TYPE_ERROR": {"TEST_ASSERTION", "BUILD_ERROR", "PACKAGE_ERROR"},
    "DEPENDENCY_ERROR": {"BUILD_ERROR", "TEST_ASSERTION", "PACKAGE_ERROR", "DEPLOYMENT_ERROR"},
    "BUILD_ERROR": {"PACKAGE_ERROR", "DEPLOYMENT_ERROR"},
    "TEST_ASSERTION": {"PACKAGE_ERROR", "DEPLOYMENT_ERROR"},
    "PACKAGE_ERROR": {"DEPLOYMENT_ERROR", "RUNTIME_ERROR"},
    "DEPLOYMENT_ERROR": {"RUNTIME_ERROR"},
}


class RootCauseRanker:
    def __init__(self, graph: PipelineGraph):
        self.graph = graph

    def rank(self, failures: list[Failure]) -> list[RankedFailure]:
        failed_by_stage = {f.stage: f for f in failures}
        max_downstream = max((len(self.graph.descendants(f.stage)) for f in failures), default=1) or 1
        max_depth = max((self.graph.depth(f.stage) for f in failures), default=1) or 1

        ranked: list[RankedFailure] = []
        for failure in failures:
            descendants = self.graph.descendants(failure.stage)
            downstream_failures = [failed_by_stage[s] for s in descendants if s in failed_by_stage]
            causal_matches = sum(
                1 for d in downstream_failures if d.error_type in CAUSE_RULES.get(failure.error_type, set())
            )
            upstream_impact = len(descendants) / max_downstream
            upstream_bonus = 1.0 - (self.graph.depth(failure.stage) / (max_depth + 1))
            causal_signal = causal_matches / max(len(downstream_failures), 1)
            criticality = self.graph.stages[failure.stage].criticality
            score = (
                0.30 * upstream_impact
                + 0.25 * failure.confidence
                + 0.20 * causal_signal
                + 0.15 * upstream_bonus
                + 0.10 * max(failure.severity, criticality)
            )
            reasons = [
                f"affects {len(descendants)} downstream stage(s)",
                f"depth={self.graph.depth(failure.stage)}",
                f"classifier confidence={failure.confidence:.2f}",
            ]
            if causal_matches:
                reasons.append(f"matches {causal_matches} downstream causal rule(s)")
            ranked.append(
                RankedFailure(
                    failure=failure,
                    score=round(score, 4),
                    downstream_count=len(descendants),
                    depth=self.graph.depth(failure.stage),
                    causal_matches=causal_matches,
                    reasons=reasons,
                )
            )
        return sorted(ranked, key=lambda item: item.score, reverse=True)

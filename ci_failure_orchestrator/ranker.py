"""Root cause ranking for CI failure analysis.

This module provides root cause ranking for CI failures using dependency graph
analysis, causal rule matching, and multi-factor scoring to prioritize failures
most likely to be the root cause of downstream issues.
"""

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
    """Ranks CI failures by their likelihood of being the root cause.

    This ranker uses dependency graph analysis, causal rule matching, and
    multi-factor scoring to prioritize failures that are most likely to be
    the root cause of downstream issues. Scoring considers upstream impact,
    classifier confidence, causal signal, upstream bonus, and severity.

    Attributes:
        graph: Pipeline dependency graph for failure analysis.

    Audit Notes:
        - Incorrect ranking may lead to repairing the wrong failure.
        - Causal rule matching is heuristic and may miss edge cases.
        - Recovery: Review ranking results and adjust scoring weights if ranking quality is poor.
        - Evidence: All rankings include score breakdown and reasoning for audit.

    Engineering Notes:
        - Trade-off: Heuristic scoring is fast but may miss complex causal relationships.
        - Design: Multi-factor scoring balances multiple signals for robust ranking.
        - Performance: Scoring is O(n) where n is the number of failures.
    """

    def __init__(self, graph: PipelineGraph):
        """Initialize the root cause ranker.

        Args:
            graph: Pipeline dependency graph for failure analysis.
        """
        self.graph = graph

    def rank(self, failures: list[Failure]) -> list[RankedFailure]:
        """Rank failures by their likelihood of being the root cause.

        This method scores each failure based on upstream impact, classifier
        confidence, causal signal, upstream bonus, and severity, then returns
        failures sorted by score in descending order.

        Args:
            failures: List of failures to rank.

        Returns:
            List of RankedFailure objects sorted by score in descending order.

        Scoring Factors:
            - Upstream impact (30%): Proportion of downstream stages affected.
            - Classifier confidence (25%): Confidence in error classification.
            - Causal signal (20%): Match to causal rules for downstream failures.
            - Upstream bonus (15%): Depth in pipeline (earlier stages get bonus).
            - Severity/criticality (10%): Failure severity and stage criticality.

        Side Effects:
            - None (pure ranking logic).

        Safety Invariants:
            - Ranking is heuristic and should inform but not dictate repair decisions.
            - Downstream failures are considered in scoring to identify root causes.
        """
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

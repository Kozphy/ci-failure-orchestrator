"""Causal edge inference for CI failure propagation analysis.

This module provides causal edge inference that identifies likely causal
relationships between failures in a CI pipeline based on error type rules,
pipeline distance, and classifier confidence.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from .graph import PipelineGraph
from .models import Failure
from .ranker import CAUSE_RULES

@dataclass(frozen=True)
class CausalEdge:
    """Causal edge representing a likely cause-effect relationship between failures.

    Attributes:
        source: Source stage ID (the likely cause).
        target: Target stage ID (the likely effect).
        confidence: Confidence in the causal relationship (0.0 to 1.0).
        evidence: Tuple of evidence tags supporting the causal relationship.
    """

    source: str
    target: str
    confidence: float
    evidence: tuple[str, ...]

    def to_dict(self):
        """Convert the causal edge to a dictionary representation.

        Returns:
            Dictionary containing all edge fields.
        """
        return asdict(self)


def infer_causal_edges(graph: PipelineGraph, failures: list[Failure]) -> list[CausalEdge]:
    """Infer causal edges between failures based on pipeline dependency graph.

    This function identifies likely causal relationships between failures by
    checking if upstream failures match causal rules for downstream failures,
    considering pipeline distance and classifier confidence.

    Args:
        graph: Pipeline dependency graph for causal analysis.
        failures: List of failures to analyze for causal relationships.

    Returns:
        List of CausalEdge objects sorted by source and target stage IDs.

    Scoring Factors:
        - Error-type causal rule match (45%): Source error type matches causal rules for target.
        - Pipeline distance (30%): Closer stages have higher causal confidence.
        - Classifier confidence (25%): Confidence in source error classification.

    Edge Threshold:
        - Only edges with confidence >= 0.45 are included in results.

    Side Effects:
        - None (pure inference logic).

    Audit Notes:
        - Incorrect causal edges may lead to repairing the wrong failure.
        - Causal rule matching is heuristic and may miss edge cases.
        - Recovery: Review causal edges and adjust scoring weights if inference quality is poor.
        - Evidence: All edges include confidence and evidence tags for audit.

    Engineering Notes:
        - Trade-off: Heuristic scoring is fast but may miss complex causal relationships.
        - Design: Only downstream stages are considered as potential effects.
        - Performance: Edge inference is O(n*m) where n and m are failure counts.
    """
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

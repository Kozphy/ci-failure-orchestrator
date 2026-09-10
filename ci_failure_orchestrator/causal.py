from __future__ import annotations

"""Causal edge inference for CI failure dependency analysis.

This module identifies likely causal relationships between failures
based on pipeline stage dependencies and error type rules. It helps
build a causal graph that explains which failures likely caused others.

Module responsibility:
    - Infer causal edges between failures in a pipeline
    - Compute edge confidence scores
    - Collect evidence supporting each causal inference

Key invariants:
    - Only failures within the same pipeline are considered
    - Source must be upstream of target in the pipeline graph
    - Causal edges are sorted by (source, target) for determinism

Safety boundaries:
    - Minimum confidence threshold of 0.45 for edge inclusion
    - Confidence is capped at 1.0
    - Only direct and indirect downstream failures are considered

Audit Notes:
    - CAUSE_RULES from ranker.py define which error types can cause others
    - Edge confidence combines: causal rule match, distance, and source confidence
    - Evidence strings explain the basis for each inference
"""

from dataclasses import dataclass, asdict

from .graph import PipelineGraph
from .models import Failure
from .ranker import CAUSE_RULES


@dataclass(frozen=True)
class CausalEdge:
    """Inferred causal edge from source failure to target failure.

    Represents a likely causal relationship where the source failure
    may have caused or contributed to the target failure.

    Attributes:
        source: Stage ID of the source (potential cause) failure
        target: Stage ID of the target (potential effect) failure
        confidence: Confidence score (0.0-1.0) in this causal relationship
        evidence: Tuple of evidence strings supporting this inference
    """

    source: str
    target: str
    confidence: float
    evidence: tuple[str, ...]

    def to_dict(self):
        """Return JSON-serializable dictionary representation.

        Returns:
            Dictionary with all edge fields
        """
        return asdict(self)


def infer_causal_edges(graph: PipelineGraph, failures: list[Failure]) -> list[CausalEdge]:
    """Infer causal edges between failures in a pipeline graph.

    For each pair of failures where source is upstream of target,
    computes a confidence score based on:
    - Error type causal rules match (45% weight)
    - Pipeline distance (30% weight, inverse relationship)
    - Source failure confidence (25% weight)

    Only edges with confidence >= 0.45 are included.

    Args:
        graph: PipelineGraph defining stage dependencies
        failures: List of Failure objects to analyze

    Returns:
        List of CausalEdge sorted by (source, target)

    Side effects:
        None.

    Audit Notes:
        - Only considers pairs where source is upstream of target
        - Confidence is capped at 1.0 even if raw score exceeds it
        - Evidence strings explain the scoring components
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

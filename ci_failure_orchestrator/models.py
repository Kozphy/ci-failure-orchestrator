from __future__ import annotations

"""Core data models for CI Failure Orchestrator.

This module defines the fundamental data structures used throughout the
platform: Stage, Failure, and RankedFailure. These models represent
the pipeline structure, failure metadata, and ranked analysis results.

Module responsibility:
    - Define Stage for pipeline dependency graph nodes
    - Define Failure for captured CI failure information
    - Define RankedFailure for root cause analysis results

Key invariants:
    - Stage.id is the unique identifier
    - Stage.depends_on defines upstream dependencies
    - Failure.stage references a Stage.id
    - RankedFailure wraps a Failure with analysis metadata

Safety boundaries:
    - All models are dataclasses with type annotations
    - Failure.metadata is a dict for extensibility
    - to_dict() methods provide JSON-serializable representations

Audit Notes:
    - Stage.criticality affects ranking weights
    - Failure.severity and confidence affect ranking scores
    - RankedFailure.score is computed, not user-provided
"""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Stage:
    """Pipeline stage definition.

    Represents a stage in the CI/CD pipeline with its dependencies
    and criticality level.

    Attributes:
        id: Unique stage identifier
        depends_on: Tuple of upstream stage IDs this stage depends on
        criticality: Criticality level (0.0-1.0) affecting ranking weights
    """

    id: str
    depends_on: tuple[str, ...] = ()
    criticality: float = 0.5


@dataclass
class Failure:
    """Captured CI failure information.

    Represents a single failure event with its stage, type, message,
    and associated metadata for analysis and ranking.

    Attributes:
        stage: ID of the Stage where this failure occurred
        error_type: Classification of the error (e.g., "BUILD_ERROR", "TEST_ASSERTION")
        message: Error message from the failure
        severity: Severity level (0.0-1.0) affecting ranking scores
        confidence: Diagnosis confidence (0.0-1.0) affecting ranking scores
        metadata: Arbitrary additional failure data
    """

    stage: str
    error_type: str
    message: str = ""
    severity: float = 0.5
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RankedFailure:
    """Ranked failure with analysis metadata.

    Wraps a Failure with computed ranking information for root
    cause analysis.

    Attributes:
        failure: The original Failure being ranked
        score: Computed ranking score (0.0-1.0)
        downstream_count: Number of downstream stages affected
        depth: Depth of this stage in the pipeline graph
        causal_matches: Number of downstream failures matching causal rules
        reasons: List of human-readable reasons for the ranking
    """

    failure: Failure
    score: float
    downstream_count: int
    depth: int
    causal_matches: int
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable dictionary representation.

        Returns:
            Dictionary with all fields, including nested failure as dict
        """
        result = asdict(self)
        result["failure"] = asdict(self.failure)
        return result

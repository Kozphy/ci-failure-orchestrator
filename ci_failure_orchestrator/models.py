"""Core data models for CI failure analysis and repair.

This module defines the fundamental data structures used throughout the CI
Failure Orchestrator for representing pipeline stages, failures, and ranked
failure candidates for root-cause analysis.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Stage:
    """Represents a pipeline stage with dependency information.

    Attributes:
        id: Unique identifier for the stage.
        depends_on: Tuple of stage IDs that this stage depends on.
        criticality: Importance score (0.0 to 1.0) for prioritization.
    """

    id: str
    depends_on: tuple[str, ...] = ()
    criticality: float = 0.5


@dataclass
class Failure:
    """Represents a CI/CD failure event.

    Attributes:
        stage: Stage ID where the failure occurred.
        error_type: Classification of the error (e.g., TYPE_ERROR, TEST_ASSERTION).
        message: Human-readable error message.
        severity: Severity score (0.0 to 1.0) for prioritization.
        confidence: Confidence score (0.0 to 1.0) in the failure classification.
        metadata: Additional context such as affected files, line numbers, etc.
    """

    stage: str
    error_type: str
    message: str = ""
    severity: float = 0.5
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RankedFailure:
    """Represents a failure with ranking metadata for root-cause analysis.

    Attributes:
        failure: The underlying failure details.
        score: Overall ranking score for this failure as a root cause.
        downstream_count: Number of stages affected by this failure.
        depth: Depth in the dependency graph.
        causal_matches: Number of causal pattern matches.
        reasons: List of explanations for the ranking score.

    Returns:
        Dictionary representation of the ranked failure including nested failure data.
    """

    failure: Failure
    score: float
    downstream_count: int
    depth: int
    causal_matches: int
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert the ranked failure to a dictionary representation.

        Returns:
            Dictionary containing all ranked failure fields with nested failure data.
        """
        result = asdict(self)
        result["failure"] = asdict(self.failure)
        return result

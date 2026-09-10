"""Persistent failure memory for CI repair operations.

This module provides the failure memory system that stores historical incidents,
retrieves similar past incidents for context, and separates successful repair
history from regression-producing fixes. Historical incidents are advisory
evidence only and never grant repair or release authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Iterable, Protocol


@dataclass(frozen=True)
class IncidentMemory:
    """Record of a past CI failure incident for historical reference.

    Attributes:
        incident_id: Unique identifier for the incident.
        error_signature: Normalized error signature for similarity matching.
        failure_class: Classification of the failure type.
        root_stage: Pipeline stage where the failure occurred.
        changed_files: Tuple of files modified during the repair attempt.
        successful_patch_summary: Summary of the successful repair (if any).
        failed_patch_summaries: Tuple of summaries from failed repair attempts.
        affected_tests: Tuple of test names affected by the failure.
        retries: Number of retry attempts for the repair.
        cost_usd: Total cost of the repair operation in USD.
        latency_ms: Total latency of the repair operation in milliseconds.
        regression_detected: Whether the repair introduced a regression.
        metadata: Additional context as key-value pairs.
    """

    incident_id: str
    error_signature: str
    failure_class: str
    root_stage: str
    changed_files: tuple[str, ...] = ()
    successful_patch_summary: str = ""
    failed_patch_summaries: tuple[str, ...] = ()
    affected_tests: tuple[str, ...] = ()
    retries: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    regression_detected: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryQuery:
    """Query for retrieving similar historical incidents.

    Attributes:
        error_signature: Error signature to match against.
        failure_class: Failure class to match against.
        root_stage: Root stage to match against.
        changed_files: Files to match against for similarity scoring.
    """

    error_signature: str
    failure_class: str
    root_stage: str
    changed_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievedIncident:
    """Historical incident retrieved from memory with similarity score.

    Attributes:
        incident: The full incident memory record.
        similarity: Similarity score (0.0 to 1.0) based on query matching.
    """

    incident: IncidentMemory
    similarity: float


class IncidentStore(Protocol):
    """Protocol for incident storage backends."""

    def add(self, incident: IncidentMemory) -> None:
        """Add an incident to the store.

        Args:
            incident: Incident memory record to store.
        """
        ...

    def all(self) -> Iterable[IncidentMemory]:
        """Retrieve all incidents from the store.

        Returns:
            Iterable of all stored incident records.
        """
        ...


class InMemoryIncidentStore:
    """In-memory implementation of incident storage for testing and development.

    This store maintains incidents in a Python list and is suitable for
    development, testing, and small-scale deployments. For production,
    consider a persistent backend like SQLiteIncidentStore.

    Attributes:
        _incidents: Internal list of stored incident records.
    """

    def __init__(self, incidents: Iterable[IncidentMemory] = ()) -> None:
        """Initialize the in-memory incident store.

        Args:
            incidents: Optional initial incidents to populate the store.
        """
        self._incidents = list(incidents)

    def add(self, incident: IncidentMemory) -> None:
        """Add an incident to the in-memory store.

        Args:
            incident: Incident memory record to store.
        """
        self._incidents.append(incident)

    def all(self) -> tuple[IncidentMemory, ...]:
        """Retrieve all incidents from the in-memory store.

        Returns:
            Tuple of all stored incident records.
        """
        return tuple(self._incidents)


def _tokens(value: str) -> set[str]:
    """Extract normalized tokens from a string for similarity matching.

    Args:
        value: String to tokenize.

    Returns:
        Set of normalized lowercase tokens.
    """
    return {token.lower() for token in value.replace("/", " ").replace("_", " ").split() if token}


def _jaccard(left: set[str], right: set[str]) -> float:
    """Calculate Jaccard similarity between two token sets.

    Args:
        left: First token set.
        right: Second token set.

    Returns:
        Jaccard similarity coefficient (0.0 to 1.0).
    """
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


class FailureMemoryAgent:
    """Retrieves prior incidents without granting repair or release authority.

    This agent provides historical context for repair planning by retrieving
    similar past incidents. It separates successful repair history from
    regression-producing fixes and provides similarity scores for ranking.
    Historical incidents are advisory evidence only and never grant repair
    or release authority.

    Attributes:
        store: IncidentStore backend for historical incident storage.

    Audit Notes:
        - Historical incidents are advisory evidence only, not execution authority.
        - Regression-producing fixes are separated and never promoted.
        - Similarity scoring uses weighted Jaccard similarity (50% signature, 20% class, 20% stage, 10% files).
        - Recovery: Review similarity scores and adjust weights if retrieval quality is poor.
        - Evidence: All retrievals include similarity scores and incident details for audit.

    Engineering Notes:
        - Trade-off: Jaccard similarity is simple but may miss semantic relationships.
        - Design: Weighted scoring prioritizes error signature over other factors.
        - Performance: In-memory store is fast but not persistent; consider SQLite for production.
    """

    def __init__(self, store: IncidentStore) -> None:
        """Initialize the failure memory agent.

        Args:
            store: IncidentStore backend for historical incident storage.
        """
        self.store = store

    def remember(self, incident: IncidentMemory) -> None:
        """Store an incident in the failure memory.

        Args:
            incident: Incident memory record to store.

        Side Effects:
            - Persists the incident to the configured store.
        """
        self.store.add(incident)

    def retrieve(self, query: MemoryQuery, *, limit: int = 5, min_similarity: float = 0.15) -> tuple[RetrievedIncident, ...]:
        """Retrieve similar historical incidents based on a query.

        This function searches the incident store for similar incidents using
        weighted Jaccard similarity across error signature, failure class,
        root stage, and changed files. Results are ranked by similarity and
        regression status (non-regression incidents preferred).

        Args:
            query: Memory query with error signature, failure class, and root stage.
            limit: Maximum number of incidents to return (default: 5).
            min_similarity: Minimum similarity threshold (default: 0.15).

        Returns:
            Tuple of retrieved incidents with similarity scores, sorted by similarity.

        Similarity Scoring:
            - Error signature: 50% weight (Jaccard similarity of tokenized signatures)
            - Failure class: 20% weight (exact match)
            - Root stage: 20% weight (exact match)
            - Changed files: 10% weight (Jaccard similarity of file sets)

        Ranking:
            - Primary: Similarity score (higher is better)
            - Secondary: Regression status (non-regression preferred)
        """
        query_files = set(query.changed_files)
        results: list[RetrievedIncident] = []
        for incident in self.store.all():
            signature_score = _jaccard(_tokens(query.error_signature), _tokens(incident.error_signature))
            class_score = 1.0 if query.failure_class == incident.failure_class else 0.0
            stage_score = 1.0 if query.root_stage == incident.root_stage else 0.0
            file_score = _jaccard(query_files, set(incident.changed_files)) if (query_files or incident.changed_files) else 1.0
            similarity = 0.50 * signature_score + 0.20 * class_score + 0.20 * stage_score + 0.10 * file_score
            if similarity >= min_similarity:
                results.append(RetrievedIncident(incident=incident, similarity=round(similarity, 6)))
        results.sort(key=lambda item: (item.similarity, not item.incident.regression_detected), reverse=True)
        return tuple(results[:limit])

    def summarize(self, retrieved: Iterable[RetrievedIncident]) -> dict[str, object]:
        """Summarize retrieved incidents for repair planning context.

        This function aggregates statistics from retrieved incidents, separating
        successful repairs from failed or regressive attempts, and provides
        historical repair summaries for context.

        Args:
            retrieved: Iterable of retrieved incidents with similarity scores.

        Returns:
            Dictionary with match count, successful match count, mean similarity,
            mean retries, mean cost, and historical repair summaries.

        Summary Fields:
            - matches: Total number of retrieved incidents.
            - successful_matches: Number of incidents with successful, non-regression repairs.
            - mean_similarity: Average similarity score across all matches.
            - mean_retries: Average retry attempts across all matches.
            - mean_cost_usd: Average cost in USD across all matches.
            - historical_repairs: Tuple of successful patch summaries for context.
        """
        items = tuple(retrieved)
        successful = tuple(item for item in items if item.incident.successful_patch_summary and not item.incident.regression_detected)
        if not items:
            return {"matches": 0, "successful_matches": 0, "mean_similarity": 0.0, "mean_retries": 0.0, "mean_cost_usd": 0.0}
        return {
            "matches": len(items),
            "successful_matches": len(successful),
            "mean_similarity": round(sum(item.similarity for item in items) / len(items), 6),
            "mean_retries": round(sum(item.incident.retries for item in items) / len(items), 3),
            "mean_cost_usd": round(sum(item.incident.cost_usd for item in items) / len(items), 6),
            "historical_repairs": tuple(item.incident.successful_patch_summary for item in successful),
        }

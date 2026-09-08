from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Iterable, Protocol


@dataclass(frozen=True)
class IncidentMemory:
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
    error_signature: str
    failure_class: str
    root_stage: str
    changed_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievedIncident:
    incident: IncidentMemory
    similarity: float


class IncidentStore(Protocol):
    def add(self, incident: IncidentMemory) -> None: ...
    def all(self) -> Iterable[IncidentMemory]: ...


class InMemoryIncidentStore:
    def __init__(self, incidents: Iterable[IncidentMemory] = ()) -> None:
        self._incidents = list(incidents)

    def add(self, incident: IncidentMemory) -> None:
        self._incidents.append(incident)

    def all(self) -> tuple[IncidentMemory, ...]:
        return tuple(self._incidents)


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in value.replace("/", " ").replace("_", " ").split() if token}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


class FailureMemoryAgent:
    """Retrieves prior incidents without granting repair or release authority."""

    def __init__(self, store: IncidentStore) -> None:
        self.store = store

    def remember(self, incident: IncidentMemory) -> None:
        self.store.add(incident)

    def retrieve(self, query: MemoryQuery, *, limit: int = 5, min_similarity: float = 0.15) -> tuple[RetrievedIncident, ...]:
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

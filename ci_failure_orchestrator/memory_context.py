from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .failure_memory import RetrievedIncident


@dataclass(frozen=True)
class MemoryContext:
    confidence_adjustment: float
    suggested_repairs: tuple[str, ...]
    affected_tests: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_count: int


def build_memory_context(
    retrieved: Iterable[RetrievedIncident],
    *,
    max_adjustment: float = 0.15,
) -> MemoryContext:
    """Convert retrieved incidents into bounded advisory planning context.

    Historical evidence may only make a small confidence adjustment and cannot
    directly approve a repair. Regressed incidents contribute warnings instead of
    positive repair evidence.
    """
    items = tuple(retrieved)
    if not items:
        return MemoryContext(0.0, (), (), (), 0)

    successful = [
        item for item in items
        if item.incident.successful_patch_summary and not item.incident.regression_detected
    ]
    regressed = [item for item in items if item.incident.regression_detected]

    weighted_support = sum(item.similarity for item in successful)
    normalization = max(1.0, sum(item.similarity for item in items))
    support_ratio = weighted_support / normalization
    confidence_adjustment = min(max_adjustment, max_adjustment * support_ratio)

    suggested_repairs = tuple(dict.fromkeys(
        item.incident.successful_patch_summary for item in successful
    ))
    affected_tests = tuple(dict.fromkeys(
        test
        for item in successful
        for test in item.incident.affected_tests
    ))
    warnings = tuple(
        f"historical incident {item.incident.incident_id} regressed after repair"
        for item in regressed
    )

    return MemoryContext(
        confidence_adjustment=round(confidence_adjustment, 6),
        suggested_repairs=suggested_repairs,
        affected_tests=affected_tests,
        warnings=warnings,
        evidence_count=len(items),
    )

"""Merge independently produced Definition of Done evidence fragments.

The collector is deliberately conservative: it never invents evidence, never
infers success from missing data, and rejects conflicting claims from different
producers. This lets CI, security, review, deployment, and documentation jobs
own only the gates they can actually prove.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class EvidenceConflict:
    """Describe incompatible claims for the same dotted evidence path."""

    path: str
    existing: Any
    incoming: Any

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable conflict representation."""

        return {
            "path": self.path,
            "existing": self.existing,
            "incoming": self.incoming,
        }


@dataclass(frozen=True)
class EvidenceCollectionResult:
    """Merged evidence plus any conflicts detected during collection."""

    evidence: dict[str, Any]
    conflicts: tuple[EvidenceConflict, ...]

    @property
    def valid(self) -> bool:
        """Return True only when no producers disagree about a gate."""

        return not self.conflicts

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable collection result."""

        return {
            "valid": self.valid,
            "evidence": self.evidence,
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
        }


def _merge_mapping(
    target: dict[str, Any],
    incoming: Mapping[str, Any],
    *,
    prefix: str,
    conflicts: list[EvidenceConflict],
) -> None:
    """Recursively merge one evidence fragment without overwriting conflicts."""

    for key, value in incoming.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in target:
            target[key] = dict(value) if isinstance(value, Mapping) else value
            continue

        existing = target[key]
        if isinstance(existing, dict) and isinstance(value, Mapping):
            _merge_mapping(existing, value, prefix=path, conflicts=conflicts)
            continue

        if existing != value:
            conflicts.append(
                EvidenceConflict(path=path, existing=existing, incoming=value)
            )


def collect_evidence(
    fragments: Iterable[Mapping[str, Any]],
) -> EvidenceCollectionResult:
    """Merge independent DoD fragments using conflict-detecting semantics.

    Producers should submit only gates they can independently prove. Missing
    gates remain missing and will therefore fail closed in the downstream DoD
    evaluator. Conflicting claims are preserved as collection failures instead
    of silently choosing one producer over another.
    """

    merged: dict[str, Any] = {}
    conflicts: list[EvidenceConflict] = []
    for fragment in fragments:
        _merge_mapping(merged, fragment, prefix="", conflicts=conflicts)

    return EvidenceCollectionResult(
        evidence=merged,
        conflicts=tuple(conflicts),
    )

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Stage:
    id: str
    depends_on: tuple[str, ...] = ()
    criticality: float = 0.5


@dataclass
class Failure:
    stage: str
    error_type: str
    message: str = ""
    severity: float = 0.5
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RankedFailure:
    failure: Failure
    score: float
    downstream_count: int
    depth: int
    causal_matches: int
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["failure"] = asdict(self.failure)
        return result

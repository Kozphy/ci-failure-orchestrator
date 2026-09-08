"""Provider-neutral protocol for CI failure intelligence and repair evidence."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid

PROTOCOL_VERSION = "0.1"


class Decision(str, Enum):
    RELEASE = "release"
    RETRY = "retry"
    BLOCK = "block"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class FailureEnvelope:
    failure_id: str
    provider: str
    repository: str
    pipeline_run_id: str
    stage: str
    failure_class: str
    root_cause_confidence: float
    log_excerpt: str = ""
    affected_nodes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    protocol_version: str = PROTOCOL_VERSION

    @classmethod
    def new(cls, **kwargs: Any) -> "FailureEnvelope":
        return cls(failure_id=str(uuid.uuid4()), **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepairEnvelope:
    repair_id: str
    failure_id: str
    agent: str
    strategy: str
    confidence: float
    estimated_cost: float
    patch_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    protocol_version: str = PROTOCOL_VERSION

    @classmethod
    def new(cls, **kwargs: Any) -> "RepairEnvelope":
        return cls(repair_id=str(uuid.uuid4()), **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvaluationEnvelope:
    repair_id: str
    passed: bool
    regression_free: bool
    score: float
    latency_ms: float
    reasons: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    protocol_version: str = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceEnvelope:
    evidence_id: str
    failure_id: str
    repair_id: str | None
    decision: Decision
    reason: str
    cumulative_cost: float
    cumulative_latency_ms: float
    attempt: int
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)
    protocol_version: str = PROTOCOL_VERSION

    @classmethod
    def new(cls, *, decision: Decision, **kwargs: Any) -> "EvidenceEnvelope":
        return cls(
            evidence_id=str(uuid.uuid4()),
            decision=decision,
            timestamp=datetime.now(timezone.utc).isoformat(),
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decision"] = self.decision.value
        return payload

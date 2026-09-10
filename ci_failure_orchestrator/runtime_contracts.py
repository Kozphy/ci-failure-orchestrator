from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .autonomous_runtime import DurableRunState


class RunStore(Protocol):
    """Persistence contract for resumable autonomous runs."""

    def save(self, state: DurableRunState) -> None: ...
    def load(self, run_id: str) -> DurableRunState | None: ...


class WorkQueue(Protocol):
    """Queue contract that can be backed by memory, Redis, SQS, Kafka, etc."""

    def enqueue(self, run_id: str) -> None: ...
    def dequeue(self) -> str | None: ...
    def dead_letter(self, run_id: str, reason: str) -> None: ...
    def replay_dead_letter(self, run_id: str) -> bool: ...


@dataclass(frozen=True)
class GateResult:
    passed: bool
    score: float = 1.0
    reason: str = ""
    metadata: dict[str, Any] | None = None


class EvaluationGate(Protocol):
    """Mandatory verification contract for EvalForge or another evaluator."""

    def evaluate(self, state: DurableRunState) -> GateResult: ...


class TelemetrySink(Protocol):
    """Minimal provider-neutral telemetry contract."""

    def counter(self, name: str, value: int = 1, **attributes: str) -> None: ...
    def histogram(self, name: str, value: float, **attributes: str) -> None: ...

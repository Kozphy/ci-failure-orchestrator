from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from .autonomous_runtime import DurableRunState, InvocationBudget, InvocationUsage
from .runtime_contracts import EvaluationGate, GateResult, RunStore, TelemetrySink, WorkQueue


class InMemoryWorkQueue:
    """Deterministic queue used for tests/local development.

    Production deployments can replace this with Redis, SQS, Service Bus,
    Kafka, or a durable workflow engine without changing the control plane.
    """

    def __init__(self) -> None:
        self._queue: deque[str] = deque()
        self._dead_letters: dict[str, str] = {}

    def enqueue(self, run_id: str) -> None:
        if run_id not in self._queue:
            self._queue.append(run_id)

    def dequeue(self) -> str | None:
        return self._queue.popleft() if self._queue else None

    def dead_letter(self, run_id: str, reason: str) -> None:
        self._dead_letters[run_id] = reason

    def replay_dead_letter(self, run_id: str) -> bool:
        if run_id not in self._dead_letters:
            return False
        del self._dead_letters[run_id]
        self.enqueue(run_id)
        return True

    @property
    def dead_letters(self) -> dict[str, str]:
        return dict(self._dead_letters)


class NullTelemetry:
    def counter(self, name: str, value: int = 1, **attributes: str) -> None:
        return None

    def histogram(self, name: str, value: float, **attributes: str) -> None:
        return None


@dataclass
class MemoryTelemetry(NullTelemetry):
    counters: dict[str, int] = field(default_factory=dict)
    histograms: dict[str, list[float]] = field(default_factory=dict)

    def counter(self, name: str, value: int = 1, **attributes: str) -> None:
        self.counters[name] = self.counters.get(name, 0) + value

    def histogram(self, name: str, value: float, **attributes: str) -> None:
        self.histograms.setdefault(name, []).append(value)


class CallableEvaluationGate:
    """Adapter for EvalForge or any externally supplied evaluation function."""

    def __init__(self, evaluator: Callable[[DurableRunState], GateResult]) -> None:
        self._evaluator = evaluator

    def evaluate(self, state: DurableRunState) -> GateResult:
        return self._evaluator(state)


@dataclass(frozen=True)
class SLOPolicy:
    min_success_rate: float = 0.99
    max_p95_latency_ms: float = 30_000.0
    max_dead_letter_rate: float = 0.01


@dataclass
class SLOSnapshot:
    total: int = 0
    succeeded: int = 0
    dead_lettered: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return 1.0 if self.total == 0 else self.succeeded / self.total

    @property
    def dead_letter_rate(self) -> float:
        return 0.0 if self.total == 0 else self.dead_lettered / self.total

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        values = sorted(self.latencies_ms)
        index = max(0, min(len(values) - 1, int(0.95 * len(values)) - 1))
        return values[index]

    def passes(self, policy: SLOPolicy) -> bool:
        return (
            self.success_rate >= policy.min_success_rate
            and self.p95_latency_ms <= policy.max_p95_latency_ms
            and self.dead_letter_rate <= policy.max_dead_letter_rate
        )


class ReliabilityRuntime:
    """Provider-neutral autonomous reliability runtime.

    The runtime deliberately separates persistence, queueing, evaluation and
    telemetry so production deployments can substitute managed infrastructure.
    Evaluation is mandatory before a run can become verified.
    """

    def __init__(
        self,
        *,
        store: RunStore,
        queue: WorkQueue,
        evaluation_gate: EvaluationGate,
        telemetry: TelemetrySink | None = None,
        budget: InvocationBudget | None = None,
    ) -> None:
        self.store = store
        self.queue = queue
        self.evaluation_gate = evaluation_gate
        self.telemetry = telemetry or NullTelemetry()
        self.budget = budget or InvocationBudget()
        self.slo = SLOSnapshot()

    def submit(self, state: DurableRunState) -> None:
        state.status = "queued"
        self.store.save(state)
        self.queue.enqueue(state.run_id)
        self.telemetry.counter("orchestrator.runs.submitted")

    def reserve_ai(self, state: DurableRunState, *, tokens: int, cost_usd: float) -> None:
        if not isinstance(state.usage, InvocationUsage):
            state.usage = InvocationUsage()
        state.usage.consume(tokens=tokens, cost_usd=cost_usd, budget=self.budget)
        self.store.save(state)
        self.telemetry.counter("orchestrator.ai.calls")
        self.telemetry.histogram("orchestrator.ai.tokens", float(tokens))
        self.telemetry.histogram("orchestrator.ai.cost_usd", cost_usd)

    def finalize_candidate(self, state: DurableRunState, *, latency_ms: float) -> GateResult:
        started = time.time()
        result = self.evaluation_gate.evaluate(state)
        elapsed_ms = max(latency_ms, (time.time() - started) * 1000.0)
        self.slo.total += 1
        self.slo.latencies_ms.append(elapsed_ms)
        self.telemetry.histogram("orchestrator.run.latency_ms", elapsed_ms)

        if result.passed:
            state.status = "verified"
            state.step = "evaluation_passed"
            state.last_error = None
            self.slo.succeeded += 1
            self.telemetry.counter("orchestrator.runs.verified")
        else:
            state.status = "dead_lettered"
            state.last_error = result.reason or "evaluation_gate_failed"
            self.slo.dead_lettered += 1
            self.queue.dead_letter(state.run_id, state.last_error)
            self.telemetry.counter("orchestrator.runs.dead_lettered")

        self.store.save(state)
        return result

    def replay(self, run_id: str) -> bool:
        state = self.store.load(run_id)
        if state is None or state.status != "dead_lettered":
            return False
        if not self.queue.replay_dead_letter(run_id):
            return False
        state.status = "queued"
        state.last_error = None
        self.store.save(state)
        self.telemetry.counter("orchestrator.dead_letters.replayed")
        return True

"""Goal-driven runtime composition for the autonomous software factory.

This module connects human intent to deterministic spec compilation, agent
execution, independent evaluation, governance, and evidence persistence. It
keeps model-backed planning behind :class:`GoalSpecProvider` while preserving
:class:`SpecCompiler` as the trust boundary before autonomous work begins.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

from .software_factory import (
    AgentRuntime,
    AutonomousSoftwareFactory,
    EvaluationResult,
    Evaluator,
    FactoryTask,
    GovernanceGate,
)
from .spec_engine import FactorySpec, SpecCompiler


@dataclass(frozen=True)
class GoalRequest:
    """Human intent and optional repository/domain context for one factory run."""

    goal: str
    context: str = ""


class GoalSpecProvider(Protocol):
    """Translate a human goal into a machine-readable :class:`FactorySpec`.

    Implementations may be model-backed or deterministic. Returned specs are
    not trusted directly; callers must pass them through :class:`SpecCompiler`.
    """

    def generate(self, request: GoalRequest) -> FactorySpec:
        """Generate a candidate structured specification for ``request``."""
        ...


@dataclass(frozen=True)
class EvidenceRecord:
    """Immutable evaluator evidence for one task attempt."""

    task_id: str
    attempt: int
    passed: bool
    evidence: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


class EvidenceStore(Protocol):
    """Persistence contract for evaluator decisions and proof artifacts."""

    def append(self, record: EvidenceRecord) -> None:
        """Persist one attempt record without changing its meaning."""
        ...

    def list(self, task_id: str | None = None) -> Sequence[EvidenceRecord]:
        """Return all evidence, optionally filtered to one task."""
        ...


@dataclass
class InMemoryEvidenceStore:
    """Process-local evidence store intended for tests and ephemeral runs."""

    records: list[EvidenceRecord] = field(default_factory=list)

    def append(self, record: EvidenceRecord) -> None:
        """Append ``record`` to in-memory history."""
        self.records.append(record)

    def list(self, task_id: str | None = None) -> list[EvidenceRecord]:
        """Return a defensive copy of stored records."""
        if task_id is None:
            return list(self.records)
        return [record for record in self.records if record.task_id == task_id]


class EvidenceEvaluator:
    """Decorate an evaluator so every decision becomes durable evidence."""

    def __init__(self, evaluator: Evaluator, store: EvidenceStore) -> None:
        """Bind the independent evaluator to its evidence store."""
        self.evaluator = evaluator
        self.store = store

    def evaluate(self, task: FactoryTask) -> EvaluationResult:
        """Evaluate ``task``, persist the result, and return it unchanged."""
        result = self.evaluator.evaluate(task)
        self.store.append(
            EvidenceRecord(
                task_id=task.id,
                attempt=task.attempts,
                passed=result.passed,
                evidence=result.evidence,
                failures=result.failures,
            )
        )
        return result


class RuntimeRouter:
    """Route tasks to pluggable agent runtimes by an explicit runtime key.

    Tasks without a runtime attribute use the configured default. Routing does
    not bypass evaluation or governance; it only selects the worker runtime.
    """

    def __init__(self, default: AgentRuntime, routes: dict[str, AgentRuntime] | None = None):
        """Configure a default runtime and optional named overrides."""
        self.default = default
        self.routes = dict(routes or {})

    def execute(self, task: FactoryTask) -> None:
        """Execute ``task`` with its named runtime or the default runtime."""
        runtime_key = getattr(task, "runtime", "default")
        runtime = self.routes.get(runtime_key, self.default)
        runtime.execute(task)


@dataclass(frozen=True)
class FactoryRunResult:
    """Complete structured output of a goal-driven factory run."""

    spec: FactorySpec
    tasks: tuple[FactoryTask, ...]
    evidence: tuple[EvidenceRecord, ...]


class GoalDrivenFactory:
    """Run the Goal -> Spec -> DAG -> Agent -> Eval -> Repair pipeline.

    The spec provider may be probabilistic, but compilation and validation are
    deterministic. Completion is determined by evaluator evidence and the
    governance gate, never by the worker agent declaring itself finished.
    """

    def __init__(
        self,
        spec_provider: GoalSpecProvider,
        runtime: AgentRuntime,
        evaluator: Evaluator,
        governance: GovernanceGate,
        *,
        compiler: SpecCompiler | None = None,
        evidence_store: EvidenceStore | None = None,
        max_attempts: int = 3,
    ) -> None:
        """Compose planning, execution, evaluation, governance, and evidence."""
        self.spec_provider = spec_provider
        self.compiler = compiler or SpecCompiler()
        self.evidence_store = evidence_store or InMemoryEvidenceStore()
        self.factory = AutonomousSoftwareFactory(
            runtime=runtime,
            evaluator=EvidenceEvaluator(evaluator, self.evidence_store),
            governance=governance,
            max_attempts=max_attempts,
        )

    def run(self, request: GoalRequest) -> FactoryRunResult:
        """Compile and execute one goal, returning tasks and evaluation evidence."""
        spec = self.spec_provider.generate(request)
        tasks = self.compiler.compile(spec)
        completed = self.factory.run(tasks)
        return FactoryRunResult(
            spec=spec,
            tasks=tuple(completed),
            evidence=tuple(self.evidence_store.list()),
        )

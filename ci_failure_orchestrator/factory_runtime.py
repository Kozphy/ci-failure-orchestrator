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
    goal: str
    context: str = ""


class GoalSpecProvider(Protocol):
    """Translate a human goal into a machine-readable FactorySpec.

    Implementations may be model-backed (Codex/Claude/Gemini/etc.) or fully
    deterministic. The SpecCompiler remains the deterministic trust boundary.
    """

    def generate(self, request: GoalRequest) -> FactorySpec: ...


@dataclass(frozen=True)
class EvidenceRecord:
    task_id: str
    attempt: int
    passed: bool
    evidence: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


class EvidenceStore(Protocol):
    def append(self, record: EvidenceRecord) -> None: ...

    def list(self, task_id: str | None = None) -> Sequence[EvidenceRecord]: ...


@dataclass
class InMemoryEvidenceStore:
    records: list[EvidenceRecord] = field(default_factory=list)

    def append(self, record: EvidenceRecord) -> None:
        self.records.append(record)

    def list(self, task_id: str | None = None) -> list[EvidenceRecord]:
        if task_id is None:
            return list(self.records)
        return [record for record in self.records if record.task_id == task_id]


class EvidenceEvaluator:
    """Wrap an evaluator and persist every decision as evidence."""

    def __init__(self, evaluator: Evaluator, store: EvidenceStore) -> None:
        self.evaluator = evaluator
        self.store = store

    def evaluate(self, task: FactoryTask) -> EvaluationResult:
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
    """Route tasks to pluggable agent runtimes by explicit runtime key."""

    def __init__(self, default: AgentRuntime, routes: dict[str, AgentRuntime] | None = None):
        self.default = default
        self.routes = dict(routes or {})

    def execute(self, task: FactoryTask) -> None:
        runtime_key = getattr(task, "runtime", "default")
        runtime = self.routes.get(runtime_key, self.default)
        runtime.execute(task)


@dataclass(frozen=True)
class FactoryRunResult:
    spec: FactorySpec
    tasks: tuple[FactoryTask, ...]
    evidence: tuple[EvidenceRecord, ...]


class GoalDrivenFactory:
    """End-to-end Goal -> Spec -> DAG -> Agent -> Eval -> Repair pipeline."""

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
        spec = self.spec_provider.generate(request)
        tasks = self.compiler.compile(spec)
        completed = self.factory.run(tasks)
        return FactoryRunResult(
            spec=spec,
            tasks=tuple(completed),
            evidence=tuple(self.evidence_store.list()),
        )

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Sequence


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AcceptanceCriterion:
    description: str
    required: bool = True


@dataclass
class FactoryTask:
    id: str
    title: str
    goal: str
    acceptance: list[AcceptanceCriterion] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    risk: str = "low"
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0


@dataclass(frozen=True)
class EvaluationResult:
    passed: bool
    evidence: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


class AgentRuntime(Protocol):
    def execute(self, task: FactoryTask) -> None: ...


class Evaluator(Protocol):
    def evaluate(self, task: FactoryTask) -> EvaluationResult: ...


class GovernanceGate(Protocol):
    def allow_autonomous_progress(self, task: FactoryTask) -> bool: ...


class AutonomousSoftwareFactory:
    """Minimal vendor-neutral software-factory loop.

    The runtime performs work, the evaluator decides correctness, and the
    governance gate controls whether the factory may continue autonomously.
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        evaluator: Evaluator,
        governance: GovernanceGate,
        *,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.runtime = runtime
        self.evaluator = evaluator
        self.governance = governance
        self.max_attempts = max_attempts

    def run(self, tasks: Sequence[FactoryTask]) -> list[FactoryTask]:
        by_id = {task.id: task for task in tasks}
        if len(by_id) != len(tasks):
            raise ValueError("task ids must be unique")

        while True:
            pending = [task for task in tasks if task.status is TaskStatus.PENDING]
            if not pending:
                break

            progressed = False
            for task in pending:
                if not self._dependencies_passed(task, by_id):
                    continue

                if not self.governance.allow_autonomous_progress(task):
                    task.status = TaskStatus.BLOCKED
                    progressed = True
                    continue

                task.status = TaskStatus.RUNNING
                while task.attempts < self.max_attempts:
                    task.attempts += 1
                    self.runtime.execute(task)
                    result = self.evaluator.evaluate(task)
                    if result.passed:
                        task.status = TaskStatus.PASSED
                        break
                else:
                    task.status = TaskStatus.FAILED

                progressed = True

            if not progressed:
                for task in pending:
                    task.status = TaskStatus.BLOCKED
                break

        return list(tasks)

    @staticmethod
    def _dependencies_passed(
        task: FactoryTask, by_id: dict[str, FactoryTask]
    ) -> bool:
        for dependency_id in task.dependencies:
            dependency = by_id.get(dependency_id)
            if dependency is None:
                raise ValueError(f"unknown dependency: {dependency_id}")
            if dependency.status is not TaskStatus.PASSED:
                return False
        return True

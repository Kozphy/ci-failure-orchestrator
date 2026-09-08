"""Core vendor-neutral execution kernel for the autonomous software factory.

The kernel separates four concerns: task state, agent execution, independent
evaluation, and governance. A worker can mutate code, but only evaluator proof
and governance policy may advance a task. Retries are bounded so autonomous
repair cannot loop forever.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Sequence


class TaskStatus(str, Enum):
    """Lifecycle states for one factory task."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AcceptanceCriterion:
    """Human- or spec-defined condition used to judge task completion."""

    description: str
    required: bool = True


@dataclass
class FactoryTask:
    """Executable unit of factory work with dependencies and risk metadata."""

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
    """Independent pass/fail decision plus supporting proof or failures."""

    passed: bool
    evidence: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


class AgentRuntime(Protocol):
    """Worker contract for performing one task attempt."""

    def execute(self, task: FactoryTask) -> None:
        """Perform one mutation/execution attempt for ``task``."""
        ...


class Evaluator(Protocol):
    """Checker contract that independently determines task correctness."""

    def evaluate(self, task: FactoryTask) -> EvaluationResult:
        """Return objective evidence for the latest task attempt."""
        ...


class GovernanceGate(Protocol):
    """Policy boundary controlling whether autonomous execution may proceed."""

    def allow_autonomous_progress(self, task: FactoryTask) -> bool:
        """Return whether ``task`` may execute without external approval."""
        ...


class AutonomousSoftwareFactory:
    """Minimal vendor-neutral execute -> evaluate -> retry factory loop.

    The runtime performs work, the evaluator decides correctness, and the
    governance gate controls authority. Tasks are attempted only after all
    dependencies pass. Failed evaluations may retry up to ``max_attempts``;
    exhausted tasks fail, while dependency deadlocks or denied autonomy block.
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        evaluator: Evaluator,
        governance: GovernanceGate,
        *,
        max_attempts: int = 3,
    ) -> None:
        """Create the factory kernel with a positive retry budget."""
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.runtime = runtime
        self.evaluator = evaluator
        self.governance = governance
        self.max_attempts = max_attempts

    def run(self, tasks: Sequence[FactoryTask]) -> list[FactoryTask]:
        """Execute dependency-ready tasks until each reaches a terminal state.

        Raises:
            ValueError: If task identifiers are duplicated or a dependency is
                missing from the supplied task set.
        """
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
        """Return whether every declared dependency has passed.

        Raises:
            ValueError: If a task references an unknown dependency.
        """
        for dependency_id in task.dependencies:
            dependency = by_id.get(dependency_id)
            if dependency is None:
                raise ValueError(f"unknown dependency: {dependency_id}")
            if dependency.status is not TaskStatus.PASSED:
                return False
        return True

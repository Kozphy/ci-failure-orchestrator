from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .software_factory import AcceptanceCriterion, FactoryTask


@dataclass(frozen=True)
class TaskSpec:
    id: str
    title: str
    goal: str
    acceptance: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    risk: str = "low"


@dataclass(frozen=True)
class FactorySpec:
    """Machine-readable intent for one autonomous engineering run."""

    goal: str
    tasks: tuple[TaskSpec, ...] = field(default_factory=tuple)


class SpecValidationError(ValueError):
    pass


class SpecCompiler:
    """Compile a validated factory specification into executable tasks.

    This intentionally does not depend on a model vendor. An LLM adapter can
    create ``FactorySpec`` later; the compiler remains deterministic and is the
    trust boundary before autonomous execution starts.
    """

    VALID_RISKS = {"low", "medium", "high", "critical"}

    def compile(self, spec: FactorySpec) -> list[FactoryTask]:
        self.validate(spec)
        return [
            FactoryTask(
                id=task.id,
                title=task.title,
                goal=task.goal,
                acceptance=[AcceptanceCriterion(item) for item in task.acceptance],
                dependencies=list(task.dependencies),
                risk=task.risk,
            )
            for task in spec.tasks
        ]

    def validate(self, spec: FactorySpec) -> None:
        if not spec.goal.strip():
            raise SpecValidationError("factory goal must not be empty")
        if not spec.tasks:
            raise SpecValidationError("factory spec must contain at least one task")

        ids = [task.id for task in spec.tasks]
        if any(not task_id.strip() for task_id in ids):
            raise SpecValidationError("task id must not be empty")
        if len(ids) != len(set(ids)):
            raise SpecValidationError("task ids must be unique")

        known = set(ids)
        for task in spec.tasks:
            if not task.title.strip() or not task.goal.strip():
                raise SpecValidationError(f"task {task.id} requires title and goal")
            if task.risk not in self.VALID_RISKS:
                raise SpecValidationError(
                    f"task {task.id} has unsupported risk: {task.risk}"
                )
            for dependency in task.dependencies:
                if dependency not in known:
                    raise SpecValidationError(
                        f"task {task.id} has unknown dependency: {dependency}"
                    )
                if dependency == task.id:
                    raise SpecValidationError(f"task {task.id} cannot depend on itself")

        self._reject_cycles(spec.tasks)

    @staticmethod
    def _reject_cycles(tasks: Iterable[TaskSpec]) -> None:
        graph = {task.id: set(task.dependencies) for task in tasks}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise SpecValidationError("task dependency graph contains a cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in graph[task_id]:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in graph:
            visit(task_id)

"""Deterministic specification compiler for autonomous engineering runs.

Model output is treated as untrusted planning input. This module validates the
machine-readable goal, task identifiers, risk values, and dependency graph
before converting the spec into executable :class:`FactoryTask` objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .software_factory import AcceptanceCriterion, FactoryTask


@dataclass(frozen=True)
class TaskSpec:
    """Declarative task definition produced before autonomous execution."""

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
    """Raised when a candidate factory specification violates trust rules."""


class SpecCompiler:
    """Validate and compile a factory specification into executable tasks.

    The compiler intentionally has no dependency on a model vendor. An LLM may
    propose :class:`FactorySpec`, but autonomous execution starts only after the
    deterministic validations in this class succeed.
    """

    VALID_RISKS = {"low", "medium", "high", "critical"}

    def compile(self, spec: FactorySpec) -> list[FactoryTask]:
        """Validate ``spec`` and convert it to fresh executable task objects."""
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
        """Reject malformed goals, tasks, risks, references, and DAG cycles.

        Raises:
            SpecValidationError: If the specification is unsafe or structurally
                invalid for deterministic autonomous execution.
        """
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
        """Reject circular task dependencies using depth-first traversal."""
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

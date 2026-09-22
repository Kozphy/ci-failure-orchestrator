"""Planner boundary — emits RepairPlan only; never mutates the repository."""

from __future__ import annotations

from typing import Protocol

from .models import (
    FailureClassification,
    FailureContext,
    PlanStep,
    RepairPlan,
    ToolRiskLevel,
    new_id,
    utc_now,
)
from .retry import RetryContext


class PlannerError(RuntimeError):
    pass


class Planner(Protocol):
    def plan(
        self,
        context: FailureContext,
        classification: FailureClassification,
        retry_context: RetryContext | None = None,
    ) -> RepairPlan: ...


class DeterministicPlanner:
    """Network-free planner for tests and local demos."""

    def plan(
        self,
        context: FailureContext,
        classification: FailureClassification,
        retry_context: RetryContext | None = None,
    ) -> RepairPlan:
        if not context.run_id:
            raise PlannerError("context.run_id required")
        steps: list[PlanStep] = [
            PlanStep(
                step_id=new_id("step"),
                action="inspect_failure_logs",
                tool="log_reader",
                inputs={
                    "excerpt": next(
                        (e for e in context.prioritized_evidence if e.startswith("log_excerpt:")),
                        "",
                    )
                },
                risk_level=ToolRiskLevel.READ_ONLY,
            )
        ]
        if context.changed_paths:
            steps.append(
                PlanStep(
                    step_id=new_id("step"),
                    action="read_related_source",
                    tool="file_reader",
                    inputs={"path": context.changed_paths[0]},
                    risk_level=ToolRiskLevel.READ_ONLY,
                )
            )
        if classification.category in {"test_failure", "lint_failure", "type_failure"}:
            steps.append(
                PlanStep(
                    step_id=new_id("step"),
                    action="run_target_verification",
                    tool="test_runner",
                    inputs={"target": "targeted"},
                    risk_level=ToolRiskLevel.RESTRICTED,
                )
            )

        risk = "low" if classification.category in {"lint_failure", "type_failure"} else "medium"
        if classification.category in {"unknown", "infrastructure_failure", "network_failure"}:
            risk = "high"

        attempt_note = ""
        if retry_context is not None and retry_context.attempt_number > 1:
            failed = "; ".join(retry_context.failed_approaches[-3:])
            attempt_note = (
                f" (retry attempt {retry_context.attempt_number}; "
                f"avoid: {failed or 'none'})"
            )

        return RepairPlan(
            run_id=context.run_id,
            goal=(
                f"Produce a minimal repair proposal for: {context.summary[:160]}"
                f"{attempt_note}"
            ),
            assumptions=(
                "Evidence is sufficient for a scoped proposal",
                "Classification confidence is heuristic",
                f"classified_as={classification.category}",
                *(
                    (f"retry_attempt={retry_context.attempt_number}",)
                    if retry_context is not None
                    else ()
                ),
            ),
            steps=tuple(steps),
            required_tools=tuple(s.tool for s in steps),
            risk_level=risk,
            verification_steps=("target_verification", "scope_check"),
            stop_conditions=("proposal_ready", "tool_failure", "classification_unknown"),
            timestamp=utc_now(),
        )


class ScriptedPlanner:
    """Returns a predetermined sequence of RepairPlan factories / plans.

    When exhausted, repeats the last plan. Network-free and deterministic.
    """

    def __init__(self, plans: list[RepairPlan] | None = None) -> None:
        self._plans = list(plans or [])
        self._index = 0
        self._fallback = DeterministicPlanner()

    def plan(
        self,
        context: FailureContext,
        classification: FailureClassification,
        retry_context: RetryContext | None = None,
    ) -> RepairPlan:
        if not self._plans:
            return self._fallback.plan(context, classification, retry_context)
        idx = min(self._index, len(self._plans) - 1)
        self._index += 1
        plan = self._plans[idx]
        # Bind run_id to current context if mismatched
        if plan.run_id != context.run_id:
            return RepairPlan(
                run_id=context.run_id,
                goal=plan.goal,
                assumptions=plan.assumptions,
                steps=plan.steps,
                required_tools=plan.required_tools,
                risk_level=plan.risk_level,
                verification_steps=plan.verification_steps,
                stop_conditions=plan.stop_conditions,
            )
        return plan


class OptionalModelPlannerAdapter:
    """Adapter placeholder for an LLM planner behind the same Protocol.

    Does not call network APIs. Inject ``delegate`` for a real model later.
    """

    def __init__(self, delegate: Planner | None = None) -> None:
        self._delegate = delegate or DeterministicPlanner()

    def plan(
        self,
        context: FailureContext,
        classification: FailureClassification,
        retry_context: RetryContext | None = None,
    ) -> RepairPlan:
        return self._delegate.plan(context, classification, retry_context)

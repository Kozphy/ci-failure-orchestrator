"""Deterministic planner boundary (no direct repository mutation)."""

from __future__ import annotations

from typing import Protocol

from .models import (
    FailureClassification,
    FailureContext,
    PlanStep,
    RepairPlan,
    ToolRiskLevel,
    utc_now,
)


class Planner(Protocol):
    def plan(self, context: FailureContext, classification: FailureClassification) -> RepairPlan:
        ...


class DeterministicPlanner:
    """Testable planner that emits bounded steps from classification."""

    def plan(self, context: FailureContext, classification: FailureClassification) -> RepairPlan:
        steps: list[PlanStep] = [
            PlanStep("inspect_logs", "log_inspection", "Collect failing log evidence", ToolRiskLevel.READ_ONLY),
        ]
        if context.changed_paths:
            steps.append(
                PlanStep(
                    "read_changed_file",
                    "file_read",
                    f"Inspect {context.changed_paths[0]}",
                    ToolRiskLevel.READ_ONLY,
                )
            )
        if classification.failure_class in {"test_failure", "lint_failure", "type_failure"}:
            steps.append(
                PlanStep(
                    "run_target_checks",
                    "test_runner",
                    "Run allowlisted verification target",
                    ToolRiskLevel.RESTRICTED,
                )
            )

        risk = "low" if classification.failure_class in {"lint_failure", "type_failure"} else "medium"
        if classification.failure_class in {"unknown", "infrastructure_failure", "network_failure"}:
            risk = "high"

        return RepairPlan(
            run_id=context.run_id,
            goal=f"Restore CI for: {context.summary[:180]}",
            assumptions=(
                "Failure evidence is complete enough for a minimal repair",
                "Confidence is heuristic unless calibrated=True",
                f"classified_as={classification.failure_class}",
            ),
            steps=tuple(steps),
            required_tools=tuple(step.tool_name for step in steps),
            risk_level=risk,
            expected_verification=("target_check", "no_forbidden_paths"),
            stop_conditions=(
                "retry_budget_exhausted",
                "policy_escalate",
                "identical_failure_repeated",
            ),
            timestamp=utc_now(),
        )

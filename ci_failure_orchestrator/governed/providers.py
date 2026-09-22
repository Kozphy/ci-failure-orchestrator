"""Provider isolation for optional LLM planning/repair."""

from __future__ import annotations

from typing import Protocol

from .models import FailureClassification, FailureContext, RepairPlan, RepairProposal


class AgentModel(Protocol):
    def generate_plan(
        self, context: FailureContext, classification: FailureClassification
    ) -> RepairPlan: ...

    def propose_repair(
        self, context: FailureContext, plan: RepairPlan
    ) -> RepairProposal: ...


class DeterministicAgentModel:
    """Fake/test model: deterministic proposals without vendor SDK coupling."""

    def generate_plan(
        self, context: FailureContext, classification: FailureClassification
    ) -> RepairPlan:
        from .planner import DeterministicPlanner

        return DeterministicPlanner().plan(context, classification)

    def propose_repair(self, context: FailureContext, plan: RepairPlan) -> RepairProposal:
        from .models import new_id, utc_now

        paths = context.changed_paths or ("src/module.py",)
        class_hint = "unknown"
        for assumption in plan.assumptions:
            if assumption.startswith("classified_as="):
                class_hint = assumption.split("=", 1)[1]
                break
        return RepairProposal(
            proposal_id=new_id("prop"),
            run_id=context.run_id,
            files_affected=paths[:3],
            proposed_patch=(
                f"--- a/{paths[0]}\n+++ b/{paths[0]}\n"
                f"@@\n+# governed repair for {class_hint}\n"
            ),
            reasoning_summary=(
                f"Minimal scoped fix for {class_hint} "
                f"(plan risk={plan.risk_level})"
            ),
            expected_impact="Restore targeted CI check without broadening scope",
            risk_classification=plan.risk_level,
            verification_plan=plan.expected_verification,
            rollback="Revert proposal patch / discard worktree",
            timestamp=utc_now(),
        )

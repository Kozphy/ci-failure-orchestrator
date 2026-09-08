from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .repair_planner import RepairPlan


@dataclass(frozen=True)
class PatchProposal:
    provider: str
    summary: str
    changed_files: tuple[str, ...]
    patch: str
    confidence: float = 0.5
    metadata: dict[str, str] = field(default_factory=dict)


class CodingAgent(Protocol):
    name: str

    def propose_patch(self, plan: RepairPlan) -> PatchProposal:
        ...


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    reason: str
    proposal: PatchProposal | None = None


class CodingAgentExecutor:
    """Policy boundary between a repair plan and a code-mutating agent.

    The executor never trusts the agent to choose arbitrary files. A proposal is
    accepted only when its changed files are within the planner's target scope.
    High-risk plans require explicit approval before the agent is invoked.
    """

    def execute(
        self,
        agent: CodingAgent,
        plan: RepairPlan,
        *,
        human_approved: bool = False,
    ) -> ExecutionResult:
        if plan.requires_human_approval and not human_approved:
            return ExecutionResult(False, "human approval required")

        proposal = agent.propose_patch(plan)
        allowed = set(plan.target_files)
        changed = set(proposal.changed_files)

        if allowed and not changed.issubset(allowed):
            return ExecutionResult(
                False,
                "agent proposal changed files outside the approved repair scope",
                proposal,
            )

        if not proposal.patch.strip():
            return ExecutionResult(False, "agent returned an empty patch", proposal)

        return ExecutionResult(True, "proposal accepted for evaluation", proposal)

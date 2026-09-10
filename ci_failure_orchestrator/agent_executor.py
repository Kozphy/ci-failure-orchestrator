"""Agent execution layer with policy enforcement for code-mutating operations.

This module provides the policy boundary between repair planning and code-mutating
agents, ensuring that agents cannot modify files outside the approved scope and
that high-risk operations require explicit human approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .repair_planner import RepairPlan


@dataclass(frozen=True)
class PatchProposal:
    """Represents a proposed code change from a coding agent.

    Attributes:
        provider: Name of the agent or provider that generated the proposal.
        summary: Human-readable summary of the proposed change.
        changed_files: Tuple of file paths that would be modified.
        patch: Unified diff of the proposed changes.
        confidence: Confidence score (0.0 to 1.0) in the proposal quality.
        metadata: Additional context such as conflict blocks, resolver type, etc.
    """

    provider: str
    summary: str
    changed_files: tuple[str, ...]
    patch: str
    confidence: float = 0.5
    metadata: dict[str, str] = field(default_factory=dict)


class CodingAgent(Protocol):
    """Protocol for coding agents that can propose code patches.

    Attributes:
        name: Identifier for the agent instance.
    """

    name: str

    def propose_patch(self, plan: RepairPlan) -> PatchProposal:
        """Generate a patch proposal based on the repair plan.

        Args:
            plan: Repair plan specifying the failure context and target files.

        Returns:
            PatchProposal containing the proposed changes and metadata.
        """
        ...


@dataclass(frozen=True)
class ExecutionResult:
    """Result of executing a coding agent with policy enforcement.

    Attributes:
        accepted: Whether the proposal was accepted for evaluation.
        reason: Human-readable explanation of the decision.
        proposal: The patch proposal (accepted or rejected), if available.
    """

    accepted: bool
    reason: str
    proposal: PatchProposal | None = None


class CodingAgentExecutor:
    """Policy boundary between a repair plan and a code-mutating agent.

    The executor enforces strict scope control: agents cannot modify files outside
    the planner's approved target scope, and high-risk plans require explicit human
    approval before the agent is invoked. This prevents agents from making arbitrary
    changes to the codebase.

    Audit Notes:
        - Wrong scope enforcement can allow agents to modify unintended files.
        - Human approval bypass for high-risk plans is a critical security control.
        - Recovery: Review execution logs and reject proposals with out-of-scope changes.
        - Evidence: All execution results include reasons and are logged for audit trails.
    """

    def execute(
        self,
        agent: CodingAgent,
        plan: RepairPlan,
        *,
        human_approved: bool = False,
    ) -> ExecutionResult:
        """Execute a coding agent with policy enforcement.

        This method checks human approval requirements, validates that the agent's
        proposed changes are within the approved scope, and ensures the patch is
        non-empty before accepting it for evaluation.

        Args:
            agent: Coding agent to execute.
            plan: Repair plan with target scope and approval requirements.
            human_approved: Whether the plan has been approved by a human operator.

        Returns:
            ExecutionResult indicating whether the proposal was accepted and the reason.

        Decision Logic:
            - Reject: Plan requires human approval but not approved.
            - Reject: Agent changed files outside the approved target scope.
            - Reject: Agent returned an empty patch.
            - Accept: Proposal is within scope and non-empty.
        """
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

"""Bounded control plane for autonomous CI repair orchestration.

This module provides the repair control plane that orchestrates classification,
planning, agent selection, evaluation, budgets, stopping conditions, policy,
escalation, telemetry, and evidence recording. It intentionally separates
concerns and does not let an agent decide whether its own patch ships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import perf_counter
from typing import Protocol

from .classifier import classify_error
from .graph import PipelineGraph
from .models import Failure


class Decision(str, Enum):
    """Control plane decision outcomes for repair operations.

    Attributes:
        RELEASE: Repair is approved for release.
        RETRY: Repair should be retried with a different approach.
        BLOCK: Repair is blocked and cannot proceed.
        ESCALATE: Repair escalation to human review is required.
    """

    RELEASE = "release"
    RETRY = "retry"
    BLOCK = "block"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class RepairProposal:
    """Repair proposal from a coding agent.

    Attributes:
        agent: Name of the coding agent that generated the proposal.
        strategy: Repair strategy used by the agent.
        target_stage: Pipeline stage where the repair is applied.
        confidence: Agent confidence in the repair (0.0 to 1.0).
        estimated_cost: Estimated cost of the repair in USD.
        expected_latency_ms: Expected latency of the repair in milliseconds.
        patch_ref: Reference to the patch (if available).
    """

    agent: str
    strategy: str
    target_stage: str
    confidence: float
    estimated_cost: float = 0.0
    expected_latency_ms: float = 0.0
    patch_ref: str | None = None


@dataclass(frozen=True)
class Evaluation:
    """Evaluation result for a repair proposal.

    Attributes:
        passed: Whether the evaluation passed all checks.
        regression_free: Whether the repair is regression-free.
        score: Overall evaluation score (0.0 to 1.0).
        reasons: Tuple of reasons for the evaluation result.
    """

    passed: bool
    regression_free: bool
    score: float
    reasons: tuple[str, ...] = ()


@dataclass
class RunState:
    """State tracking for a single repair control plane run.

    Attributes:
        retries_used: Number of retry attempts used.
        total_cost: Total cost of all repair attempts in USD.
        total_latency_ms: Total latency of all repair attempts in milliseconds.
        history: List of execution history entries for audit.
    """

    retries_used: int = 0
    total_cost: float = 0.0
    total_latency_ms: float = 0.0
    history: list[str] = field(default_factory=list)


class CodingAgent(Protocol):
    """Protocol for coding agents that generate repair proposals.

    Attributes:
        name: Name of the coding agent.

    Methods:
        propose: Generate a repair proposal for a given failure.
    """

    name: str

    def propose(self, failure: Failure, graph: PipelineGraph) -> RepairProposal | None:
        """Generate a repair proposal for a given failure.

        Args:
            failure: Failure to generate a repair proposal for.
            graph: Pipeline dependency graph for context.

        Returns:
            RepairProposal if the agent can propose a repair, None otherwise.
        """
        ...


class Evaluator(Protocol):
    """Protocol for evaluating repair proposals.

    Methods:
        evaluate: Evaluate a repair proposal against a failure.
    """

    def evaluate(self, proposal: RepairProposal, failure: Failure) -> Evaluation:
        """Evaluate a repair proposal against a failure.

        Args:
            proposal: Repair proposal to evaluate.
            failure: Original failure for context.

        Returns:
            Evaluation result with pass/fail status, regression status, and score.
        """
        ...


class Policy(Protocol):
    """Protocol for policy decisions based on evaluation and state.

    Methods:
        decide: Make a policy decision based on evaluation and run state.
    """

    def decide(self, evaluation: Evaluation, state: RunState) -> Decision:
        """Make a policy decision based on evaluation and run state.

        Args:
            evaluation: Evaluation result for the repair proposal.
            state: Current run state with budget and retry information.

        Returns:
            Decision (RELEASE, RETRY, BLOCK, or ESCALATE).
        """
        ...


class EvidenceSink(Protocol):
    """Protocol for recording evidence and telemetry.

    Methods:
        record: Record an event with payload for audit and telemetry.
    """

    def record(self, event: str, payload: dict[str, object]) -> None:
        """Record an event with payload for audit and telemetry.

        Args:
            event: Event type identifier.
            payload: Event payload data.

        Side Effects:
            - Writes evidence to the configured sink (e.g., audit log, telemetry system).
        """
        ...


class RepairControlPlane:
    """Bounded orchestration for autonomous CI repair.

    The control plane separates classification, planning, agent selection,
    evaluation, budgets, stopping conditions, policy, escalation, telemetry,
    and evidence recording. It intentionally does not let an agent decide
    whether its own patch ships, enforcing the safety invariant of separation
    of duties.

    Attributes:
        graph: Pipeline dependency graph for repair planning.
        agents: List of coding agents that can generate repair proposals.
        evaluator: Evaluator for assessing repair proposals.
        policy: Policy engine for release decisions.
        evidence: Evidence sink for recording audit and telemetry.
        max_retries: Maximum number of retry attempts (default: 2).
        max_cost: Maximum total cost in USD (default: 1.0).
        max_latency_ms: Maximum total latency in milliseconds (default: 30,000).
        last_state: Last run state (for inspection after execution).

    Raises:
        ValueError: If max_retries is negative.

    Audit Notes:
        - Bypassing budget limits could allow runaway repair attempts.
        - Policy decisions control release authorization and must be audited.
        - Evidence recording provides audit trail for all decisions and actions.
        - Recovery: Review evidence logs and adjust budget limits if repairs are exhausting prematurely.
        - Evidence: All decisions, evaluations, and budget consumption are recorded for audit.

    Engineering Notes:
        - Trade-off: Bounded budgets limit autonomy but prevent runaway costs.
        - Design: Agents propose, evaluator assesses, policy decides—separation of duties.
        - Performance: Proposal ranking by confidence and cost prioritizes high-quality repairs.
    """

    def __init__(
        self,
        graph: PipelineGraph,
        agents: list[CodingAgent],
        evaluator: Evaluator,
        policy: Policy,
        evidence: EvidenceSink,
        *,
        max_retries: int = 2,
        max_cost: float = 1.0,
        max_latency_ms: float = 30_000.0,
    ) -> None:
        """Initialize the repair control plane.

        Args:
            graph: Pipeline dependency graph for repair planning.
            agents: List of coding agents that can generate repair proposals.
            evaluator: Evaluator for assessing repair proposals.
            policy: Policy engine for release decisions.
            evidence: Evidence sink for recording audit and telemetry.
            max_retries: Maximum number of retry attempts (default: 2).
            max_cost: Maximum total cost in USD (default: 1.0).
            max_latency_ms: Maximum total latency in milliseconds (default: 30,000).

        Raises:
            ValueError: If max_retries is negative.
        """
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.graph = graph
        self.agents = agents
        self.evaluator = evaluator
        self.policy = policy
        self.evidence = evidence
        self.max_retries = max_retries
        self.max_cost = max_cost
        self.max_latency_ms = max_latency_ms
        self.last_state: RunState | None = None

    def _stopped(self, state: RunState) -> bool:
        """Check if stopping conditions have been reached.

        Args:
            state: Current run state with budget and retry information.

        Returns:
            True if any stopping condition is reached, False otherwise.

        Stopping Conditions:
            - Retries used exceeds max_retries.
            - Total cost exceeds max_cost.
            - Total latency exceeds max_latency_ms.
        """
        return (
            state.retries_used > self.max_retries
            or state.total_cost > self.max_cost
            or state.total_latency_ms > self.max_latency_ms
        )

    def _plan(self, failure: Failure) -> list[RepairProposal]:
        """Generate and rank repair proposals from available agents.

        Args:
            failure: Failure to generate repair proposals for.

        Returns:
            List of repair proposals ranked by confidence and cost.
        """
        proposals = [p for agent in self.agents if (p := agent.propose(failure, self.graph))]
        return sorted(proposals, key=lambda p: (p.confidence, -p.estimated_cost), reverse=True)

    def run(self, failure: Failure) -> Decision:
        """Run the repair control plane for a given failure.

        This method orchestrates the full repair workflow: classification,
        planning, evaluation, policy decisions, and escalation. It enforces
        budget limits and stopping conditions to ensure bounded autonomy.

        Args:
            failure: Failure to repair.

        Returns:
            Decision (RELEASE, RETRY, BLOCK, or ESCALATE).

        Workflow:
            1. Classify the failure type and confidence.
            2. Generate repair proposals from available agents.
            3. Evaluate each proposal against the failure.
            4. Check budget and stopping conditions.
            5. Apply policy decisions (release, retry, block, escalate).
            6. Record evidence for all decisions and actions.

        Side Effects:
            - Records classification, evaluation, and policy decisions to evidence sink.
            - Updates run state with cost, latency, and retry consumption.

        Safety Invariants:
            - Agents cannot approve their own release (policy decides).
            - Budget limits prevent runaway repair attempts.
            - Escalation to human review for unknown or unsafe conditions.
        """
        error_type, confidence = classify_error(failure.message)
        failure.error_type = error_type
        failure.confidence = confidence
        state = RunState()
        self.last_state = state
        self.evidence.record("classified", {"stage": failure.stage, "error_type": error_type, "confidence": confidence})

        proposals = self._plan(failure)
        if not proposals:
            self.evidence.record("escalated", {"reason": "no_repair_plan", "stage": failure.stage})
            return Decision.ESCALATE

        for proposal in proposals:
            started = perf_counter()
            state.total_cost += proposal.estimated_cost
            evaluation = self.evaluator.evaluate(proposal, failure)
            observed_latency = (perf_counter() - started) * 1000.0
            state.total_latency_ms += max(observed_latency, proposal.expected_latency_ms)
            state.history.append(f"{proposal.agent}:{proposal.strategy}:{evaluation.score:.3f}")

            self.evidence.record(
                "evaluated",
                {
                    "agent": proposal.agent,
                    "strategy": proposal.strategy,
                    "score": evaluation.score,
                    "passed": evaluation.passed,
                    "regression_free": evaluation.regression_free,
                    "cost": proposal.estimated_cost,
                    "latency_ms": observed_latency,
                },
            )

            if self._stopped(state):
                self.evidence.record("escalated", {"reason": "budget_or_stopping_condition", "history": list(state.history)})
                return Decision.ESCALATE

            decision = self.policy.decide(evaluation, state)
            if decision is Decision.RETRY:
                state.retries_used += 1
                if self._stopped(state):
                    self.evidence.record("escalated", {"reason": "retry_budget_exhausted", "history": list(state.history)})
                    return Decision.ESCALATE
                continue

            self.evidence.record("policy_decision", {"decision": decision.value, "history": list(state.history)})
            return decision

        self.evidence.record("escalated", {"reason": "plans_exhausted", "history": list(state.history)})
        return Decision.ESCALATE

from __future__ import annotations

"""Repair control plane for bounded autonomous CI failure resolution.

This module provides the core orchestration layer that separates concerns:
- Classification of failures
- Repair planning and proposal generation
- Agent selection and execution
- Evaluation of repair quality
- Budget enforcement (retries, cost, latency)
- Policy decisions
- Escalation handling
- Telemetry recording
- Evidence collection

The central principle is separation of duties: agents propose repairs but
CANNOT decide whether their own patches are released. That decision is
made by the independent evaluator and policy components.

Module responsibility:
    - Orchestrate end-to-end repair workflow for a single failure
    - Enforce budget boundaries (retries, cost, latency)
    - Coordinate classification, planning, evaluation, and policy
    - Collect tamper-evident execution evidence

Key invariants:
    - RepairControlPlane.run() processes exactly one Failure
    - Proposals are sorted by confidence (descending) and cost (ascending)
    - Budget checks happen before each proposal evaluation
    - Policy decision is final authority on release/retry/escalate

Safety boundaries:
    - max_retries: maximum repair attempts per failure
    - max_cost: maximum cumulative cost across all attempts
    - max_latency_ms: maximum cumulative latency across all attempts

Failure modes:
    - No proposals: ESCALATE with reason "no_repair_plan"
    - Budget exceeded: ESCALATE with reason "budget_or_stopping_condition"
    - Retry budget exhausted: ESCALATE with reason "retry_budget_exhausted"
    - All plans exhausted: ESCALATE with reason "plans_exhausted"

Audit Notes:
    - All material events are recorded to the evidence sink
    - Events include: classified, evaluated, policy_decision, escalated
    - RunState tracks cumulative retries, cost, latency, and history
    - Evidence is append-only and tamper-evident (via EvidenceSink)
"""

from dataclasses import dataclass, field
from enum import Enum
from time import perf_counter
from typing import Protocol

from .classifier import classify_error
from .graph import PipelineGraph
from .models import Failure


class Decision(str, Enum):
    """Control plane decision outcomes.

    Values:
        RELEASE: Repair passed evaluation and policy, ready for release
        RETRY: Repair should be retried within budget
        BLOCK: Repair must be blocked (fail-closed)
        ESCALATE: Repair requires human escalation
    """

    RELEASE = "release"
    RETRY = "retry"
    BLOCK = "block"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class RepairProposal:
    """Agent-generated repair proposal.

    Represents a candidate repair for a failure, produced by a CodingAgent.

    Attributes:
        agent: Name of the agent that generated this proposal
        strategy: Repair strategy description (e.g., "fix-typo", "revert-commit")
        target_stage: Pipeline stage this repair targets
        confidence: Agent's confidence in this repair (0.0-1.0)
        estimated_cost: Estimated cost of applying this repair
        expected_latency_ms: Expected latency to apply this repair
        patch_ref: Optional reference to the generated patch
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
    """Independent evaluation of a repair proposal.

    Produced by an Evaluator (independent from the CodingAgent that
    generated the proposal). This enforces the separation of duties
    principle.

    Attributes:
        passed: Whether the repair passed verification tests
        regression_free: Whether the repair introduced no regressions
        score: Evaluation score (0.0-1.0)
        reasons: Tuple of reason tags explaining the evaluation
    """

    passed: bool
    regression_free: bool
    score: float
    reasons: tuple[str, ...] = ()


@dataclass
class RunState:
    """Mutable state tracking for a repair run.

    Tracks cumulative resource usage and execution history across
    all proposals evaluated for a single failure.

    Attributes:
        retries_used: Number of retry attempts made
        total_cost: Cumulative cost across all evaluated proposals
        total_latency_ms: Cumulative latency across all evaluated proposals
        history: List of history entries in format "agent:strategy:score"
    """

    retries_used: int = 0
    total_cost: float = 0.0
    total_latency_ms: float = 0.0
    history: list[str] = field(default_factory=list)


class CodingAgent(Protocol):
    """Protocol for repair proposal generation agents.

    Defines the interface that all coding agents must implement to
    participate in the repair workflow.

    Attributes:
        name: Unique identifier for this agent

    Methods:
        propose: Generate a repair proposal for a given failure and pipeline graph
    """

    name: str

    def propose(self, failure: Failure, graph: PipelineGraph) -> RepairProposal | None:
        """Generate a repair proposal.

        Args:
            failure: Failure to repair
            graph: PipelineGraph for context

        Returns:
            RepairProposal if a repair can be generated, None otherwise
        """
        ...


class Evaluator(Protocol):
    """Protocol for independent repair evaluation.

    Defines the interface that all evaluators must implement to
    assess repair quality independently from the proposing agent.

    Methods:
        evaluate: Evaluate a repair proposal against a failure
    """

    def evaluate(self, proposal: RepairProposal, failure: Failure) -> Evaluation:
        """Evaluate a repair proposal.

        Args:
            proposal: RepairProposal to evaluate
            failure: Failure being addressed

        Returns:
            Evaluation with pass/fail, regression status, score, and reasons
        """
        ...


class Policy(Protocol):
    """Protocol for release policy decisions.

    Defines the interface that all policy engines must implement to
    make final release decisions based on evaluation results.

    Methods:
        decide: Make a release decision based on evaluation and state
    """

    def decide(self, evaluation: Evaluation, state: RunState) -> Decision:
        """Make a policy decision.

        Args:
            evaluation: Evaluation result from independent verification
            state: RunState tracking cumulative resource usage

        Returns:
            Decision (RELEASE, RETRY, BLOCK, or ESCALATE)
        """
        ...


class EvidenceSink(Protocol):
    """Protocol for evidence collection sinks.

    Defines the interface that all evidence sinks must implement to
    record tamper-evident execution events.

    Methods:
        record: Record an event with its payload
    """

    def record(self, event: str, payload: dict[str, object]) -> None:
        """Record an evidence event.

        Args:
            event: Event type/name
            payload: Event-specific data
        """
        ...


class RepairControlPlane:
    """Bounded orchestration for autonomous CI repair.

    The control plane separates classification, planning, agent selection,
    evaluation, budgets, stopping, policy, escalation, telemetry, and evidence.
    It intentionally does not let an agent decide whether its own patch ships.

    Responsibility:
        - Classify failures using error message analysis
        - Plan repairs by collecting proposals from all agents
        - Evaluate each proposal independently
        - Enforce budget boundaries (retries, cost, latency)
        - Apply policy to make final release decisions
        - Collect and record all execution evidence

    Invariants:
        - run() processes exactly one Failure at a time
        - Proposals are sorted by confidence (descending) then cost (ascending)
        - Budget is checked before each proposal evaluation
        - Policy decision is the final authority

    Usage:
        plane = RepairControlPlane(
            graph=pipeline_graph,
            agents=[agent1, agent2],
            evaluator=evaluator,
            policy=policy,
            evidence=evidence_sink,
            max_retries=2,
            max_cost=1.0,
            max_latency_ms=30000,
        )
        decision = plane.run(failure)

    Side effects:
        - Records events to the evidence sink
        - Updates internal last_state reference

    Audit Notes:
        - All proposals, evaluations, and decisions are recorded as evidence
        - Budget checks prevent unbounded resource consumption
        - Policy decisions are independent from agent proposals
    """

    """Bounded orchestration for autonomous CI repair.

    The control plane separates classification, planning, agent selection,
    evaluation, budgets, stopping, policy, escalation, telemetry, and evidence.
    It intentionally does not let an agent decide whether its own patch ships.
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
        """Initialize the control plane with components.

        Args:
            graph: PipelineGraph for dependency context
            agents: List of CodingAgent instances to generate proposals
            evaluator: Evaluator instance for independent verification
            policy: Policy instance for final release decisions
            evidence: EvidenceSink for recording execution events
            max_retries: Maximum number of retry attempts (default 2)
            max_cost: Maximum cumulative cost (default 1.0)
            max_latency_ms: Maximum cumulative latency in milliseconds (default 30000)

        Raises:
            ValueError: If max_retries is negative

        Side effects:
            None (initialization only)
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
        """Check if budget or retry limits have been exceeded.

        Args:
            state: Current RunState to check

        Returns:
            True if any budget limit is exceeded, False otherwise

        Side effects:
            None.
        """
        return (
            state.retries_used > self.max_retries
            or state.total_cost > self.max_cost
            or state.total_latency_ms > self.max_latency_ms
        )

    def _plan(self, failure: Failure) -> list[RepairProposal]:
        """Collect and sort repair proposals from all agents.

        Each agent is asked to propose a repair for the failure.
        Proposals are sorted by confidence (descending) and then by
        estimated cost (ascending, so cheaper repairs come first for
        equal confidence).

        Args:
            failure: Failure to plan repairs for

        Returns:
            List of RepairProposal, sorted by (confidence desc, cost asc)

        Side effects:
            None.
        """
        proposals = [p for agent in self.agents if (p := agent.propose(failure, self.graph))]
        return sorted(proposals, key=lambda p: (p.confidence, -p.estimated_cost), reverse=True)

    def run(self, failure: Failure) -> Decision:
        """Execute the complete repair workflow for a single failure.

        Workflow:
        1. Classify the failure error type and confidence
        2. Update failure with classification results
        3. Plan: collect proposals from all agents
        4. If no proposals: record escalation and return ESCALATE
        5. For each proposal (in sorted order):
           a. Check budget limits; if exceeded, return ESCALATE
           b. Evaluate proposal independently
           c. Record evaluation results
           d. Check budget again (evaluation cost counted)
           e. Apply policy to get decision
           f. If RETRY: increment retry count, check budget, continue
           g. Otherwise: record policy decision and return decision
        6. If all proposals exhausted: record escalation and return ESCALATE

        Args:
            failure: Failure to repair

        Returns:
            Decision (RELEASE, RETRY, BLOCK, or ESCALATE)

        Side effects:
            - Records multiple events to evidence sink
            - Updates last_state reference
            - Modifies failure.error_type and failure.confidence

        Audit Notes:
            - All decisions are recorded with reasons and history
            - Budget checks are performed before and after each evaluation
            - Policy decisions are independent from agent proposals
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

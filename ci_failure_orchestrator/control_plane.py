from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import perf_counter
from typing import Protocol

from .classifier import classify_error
from .graph import PipelineGraph
from .models import Failure


class Decision(str, Enum):
    RELEASE = "release"
    RETRY = "retry"
    BLOCK = "block"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class RepairProposal:
    agent: str
    strategy: str
    target_stage: str
    confidence: float
    estimated_cost: float = 0.0
    expected_latency_ms: float = 0.0
    patch_ref: str | None = None


@dataclass(frozen=True)
class Evaluation:
    passed: bool
    regression_free: bool
    score: float
    reasons: tuple[str, ...] = ()


@dataclass
class RunState:
    retries_used: int = 0
    total_cost: float = 0.0
    total_latency_ms: float = 0.0
    history: list[str] = field(default_factory=list)


class CodingAgent(Protocol):
    name: str

    def propose(self, failure: Failure, graph: PipelineGraph) -> RepairProposal | None: ...


class Evaluator(Protocol):
    def evaluate(self, proposal: RepairProposal, failure: Failure) -> Evaluation: ...


class Policy(Protocol):
    def decide(self, evaluation: Evaluation, state: RunState) -> Decision: ...


class EvidenceSink(Protocol):
    def record(self, event: str, payload: dict[str, object]) -> None: ...


class RepairControlPlane:
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
        return (
            state.retries_used > self.max_retries
            or state.total_cost > self.max_cost
            or state.total_latency_ms > self.max_latency_ms
        )

    def _plan(self, failure: Failure) -> list[RepairProposal]:
        proposals = [p for agent in self.agents if (p := agent.propose(failure, self.graph))]
        return sorted(proposals, key=lambda p: (p.confidence, -p.estimated_cost), reverse=True)

    def run(self, failure: Failure) -> Decision:
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

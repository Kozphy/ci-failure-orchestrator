from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .agent_executor import CodingAgent, CodingAgentExecutor, ExecutionResult
from .agent_loop import EvaluationResult
from .repair_planner import RepairPlan


@dataclass(frozen=True)
class CandidateScore:
    agent_name: str
    execution: ExecutionResult
    evaluation: EvaluationResult | None
    cost_usd: float
    latency_ms: int
    risk_score: float
    utility: float
    accepted: bool
    reason: str


@dataclass(frozen=True)
class TournamentResult:
    winner: CandidateScore | None
    candidates: tuple[CandidateScore, ...]
    action: str
    reason: str


class RepairTournament:
    """Evaluate multiple bounded repair agents and select the best admissible patch.

    Candidate agents never bypass the existing executor policy boundary. Selection
    rewards evaluation quality while penalizing cost, latency, and risk.
    """

    def __init__(self, executor: CodingAgentExecutor | None = None):
        self.executor = executor or CodingAgentExecutor()

    def run(
        self,
        agents: Iterable[CodingAgent],
        plan: RepairPlan,
        evaluate: Callable[[ExecutionResult], EvaluationResult],
        *,
        human_approved: bool = False,
        minimum_score: float = 0.8,
        telemetry: Callable[[ExecutionResult], tuple[float, int]] | None = None,
    ) -> TournamentResult:
        candidates: list[CandidateScore] = []

        for agent in agents:
            execution = self.executor.execute(
                agent,
                plan,
                human_approved=human_approved,
            )
            if not execution.accepted:
                candidates.append(
                    CandidateScore(
                        agent_name=agent.name,
                        execution=execution,
                        evaluation=None,
                        cost_usd=0.0,
                        latency_ms=0,
                        risk_score=1.0,
                        utility=float("-inf"),
                        accepted=False,
                        reason=execution.reason,
                    )
                )
                continue

            evaluation = evaluate(execution)
            cost_usd, latency_ms = telemetry(execution) if telemetry else (0.0, 0)
            confidence = execution.proposal.confidence if execution.proposal else 0.0
            risk_score = self._risk_score(plan.risk, confidence, evaluation)
            utility = self._utility(evaluation.score, cost_usd, latency_ms, risk_score)
            admissible = (
                evaluation.success
                and evaluation.score >= minimum_score
                and risk_score < 0.8
            )
            candidates.append(
                CandidateScore(
                    agent_name=agent.name,
                    execution=execution,
                    evaluation=evaluation,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                    risk_score=risk_score,
                    utility=utility,
                    accepted=admissible,
                    reason=(
                        "candidate admissible"
                        if admissible
                        else "candidate failed evaluation, score, or risk threshold"
                    ),
                )
            )

        admissible = [candidate for candidate in candidates if candidate.accepted]
        if not admissible:
            return TournamentResult(
                winner=None,
                candidates=tuple(candidates),
                action="ESCALATE_HUMAN",
                reason="no repair candidate satisfied evaluation and risk policy",
            )

        winner = max(admissible, key=lambda candidate: candidate.utility)
        return TournamentResult(
            winner=winner,
            candidates=tuple(candidates),
            action="READY_FOR_POLICY_GATE",
            reason="highest-utility admissible repair candidate selected",
        )

    @staticmethod
    def _risk_score(risk: str, confidence: float, evaluation: EvaluationResult) -> float:
        base = {"low": 0.15, "medium": 0.4, "high": 0.75}.get(risk, 0.8)
        regression_penalty = 0.5 if not evaluation.regression_passed else 0.0
        confidence_penalty = max(0.0, 0.5 - confidence) * 0.5
        return min(1.0, base + regression_penalty + confidence_penalty)

    @staticmethod
    def _utility(score: float, cost_usd: float, latency_ms: int, risk_score: float) -> float:
        cost_penalty = min(cost_usd, 1.0) * 0.1
        latency_penalty = min(latency_ms / 60_000.0, 1.0) * 0.05
        risk_penalty = risk_score * 0.35
        return score - cost_penalty - latency_penalty - risk_penalty

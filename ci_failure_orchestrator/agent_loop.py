from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .agent_executor import CodingAgent, CodingAgentExecutor, ExecutionResult
from .evaluator import RetryBudget
from .repair_planner import RepairPlan


@dataclass(frozen=True)
class EvaluationResult:
    targeted_passed: bool
    regression_passed: bool
    score: float
    reason: str

    @property
    def success(self) -> bool:
        return self.targeted_passed and self.regression_passed


@dataclass(frozen=True)
class LoopResult:
    action: str
    attempts: int
    evaluation: EvaluationResult | None
    execution: ExecutionResult | None
    reason: str


class AgentRepairLoop:
    """Bounded repair loop with independent evaluation and explicit stopping rules."""

    def __init__(self, executor: CodingAgentExecutor | None = None):
        self.executor = executor or CodingAgentExecutor()

    def run(
        self,
        agent: CodingAgent,
        plan: RepairPlan,
        evaluate: Callable[[ExecutionResult], EvaluationResult],
        *,
        budget: RetryBudget | None = None,
        human_approved: bool = False,
        minimum_score: float = 0.8,
    ) -> LoopResult:
        budget = budget or RetryBudget()
        last_execution: ExecutionResult | None = None
        last_evaluation: EvaluationResult | None = None

        while budget.consume():
            last_execution = self.executor.execute(
                agent,
                plan,
                human_approved=human_approved,
            )

            if not last_execution.accepted:
                return LoopResult(
                    "ESCALATE_HUMAN",
                    budget.attempts,
                    None,
                    last_execution,
                    last_execution.reason,
                )

            last_evaluation = evaluate(last_execution)

            if last_evaluation.success and last_evaluation.score >= minimum_score:
                return LoopResult(
                    "READY_FOR_POLICY_GATE",
                    budget.attempts,
                    last_evaluation,
                    last_execution,
                    "repair satisfied targeted and regression evaluation",
                )

            if not last_evaluation.regression_passed:
                return LoopResult(
                    "ROLLBACK_AND_ESCALATE",
                    budget.attempts,
                    last_evaluation,
                    last_execution,
                    "repair introduced or exposed a regression",
                )

        return LoopResult(
            "ESCALATE_HUMAN",
            budget.attempts,
            last_evaluation,
            last_execution,
            "retry budget exhausted",
        )

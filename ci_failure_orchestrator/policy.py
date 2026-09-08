from __future__ import annotations

from dataclasses import dataclass

from .control_plane import Decision, Evaluation, RunState
from .tournament import CandidateScore, TournamentResult


class DefaultRepairPolicy:
    """Fail-closed release policy for the bounded autonomous control plane."""

    def __init__(self, *, release_score: float = 0.90, retry_score: float = 0.60) -> None:
        self.release_score = release_score
        self.retry_score = retry_score

    def decide(self, evaluation: Evaluation, state: RunState) -> Decision:
        if not evaluation.regression_free:
            return Decision.BLOCK
        if evaluation.passed and evaluation.score >= self.release_score:
            return Decision.RELEASE
        if evaluation.score >= self.retry_score:
            return Decision.RETRY
        return Decision.ESCALATE


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    reason: str
    requires_human_approval: bool


class RepairPolicyGate:
    """Final release boundary for tournament-selected, independently evaluated repairs."""

    def __init__(
        self,
        *,
        max_risk_score: float = 0.6,
        max_cost_usd: float = 0.50,
        max_latency_ms: int = 60_000,
    ) -> None:
        self.max_risk_score = max_risk_score
        self.max_cost_usd = max_cost_usd
        self.max_latency_ms = max_latency_ms

    def decide(self, result: TournamentResult) -> PolicyDecision:
        winner = result.winner
        if (
            winner is None
            or not winner.accepted
            or result.action != "READY_FOR_POLICY_GATE"
        ):
            return PolicyDecision("ESCALATE_HUMAN", result.reason, True)
        if not self._within_budget(winner):
            return PolicyDecision(
                "HUMAN_APPROVAL_REQUIRED",
                "winning candidate exceeds automated risk, cost, or latency policy",
                True,
            )
        if winner.evaluation is None or not winner.evaluation.success:
            return PolicyDecision(
                "BLOCK",
                "winning candidate lacks successful independent evaluation",
                True,
            )
        return PolicyDecision(
            "READY_FOR_CANARY",
            "winning candidate passed evaluation and automated policy limits",
            False,
        )

    def _within_budget(self, candidate: CandidateScore) -> bool:
        return (
            0 <= candidate.risk_score <= self.max_risk_score
            and 0 <= candidate.cost_usd <= self.max_cost_usd
            and 0 <= candidate.latency_ms <= self.max_latency_ms
        )

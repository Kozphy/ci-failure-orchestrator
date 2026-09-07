from __future__ import annotations

from dataclasses import dataclass

from .tournament import CandidateScore, TournamentResult


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    reason: str
    requires_human_approval: bool


class RepairPolicyGate:
    """Final release decision boundary for evaluated repair candidates."""

    def __init__(
        self,
        *,
        max_risk_score: float = 0.6,
        max_cost_usd: float = 0.50,
        max_latency_ms: int = 60_000,
    ):
        self.max_risk_score = max_risk_score
        self.max_cost_usd = max_cost_usd
        self.max_latency_ms = max_latency_ms

    def decide(self, result: TournamentResult) -> PolicyDecision:
        winner = result.winner
        if winner is None:
            return PolicyDecision(
                "ESCALATE_HUMAN",
                result.reason,
                True,
            )

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
            candidate.risk_score <= self.max_risk_score
            and candidate.cost_usd <= self.max_cost_usd
            and candidate.latency_ms <= self.max_latency_ms
        )

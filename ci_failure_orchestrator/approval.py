from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUIRED = "required"


@dataclass(frozen=True)
class ApprovalContext:
    policy_decision: str
    evaluation_score: float
    regression_free: bool
    changed_files: tuple[str, ...]
    high_risk_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovalResult:
    decision: ApprovalDecision
    reason: str


class HumanApprovalGate:
    """Determines whether a verified repair still requires human approval."""

    def __init__(self, *, score_threshold: float = 0.97, high_risk_prefixes: tuple[str, ...] = (".github/", "infra/", "migrations/", "security/")):
        self.score_threshold = score_threshold
        self.high_risk_prefixes = high_risk_prefixes

    def evaluate(self, context: ApprovalContext, *, human_approved: bool | None = None) -> ApprovalResult:
        if context.policy_decision != "release":
            return ApprovalResult(ApprovalDecision.REJECTED, "policy did not authorize release")
        if not context.regression_free:
            return ApprovalResult(ApprovalDecision.REJECTED, "regression detected")

        risk_paths = tuple(
            path for path in context.changed_files
            if path.startswith(self.high_risk_prefixes)
        )
        requires_human = bool(risk_paths) or context.evaluation_score < self.score_threshold

        if not requires_human:
            return ApprovalResult(ApprovalDecision.APPROVED, "low-risk repair passed automated gate")
        if human_approved is True:
            return ApprovalResult(ApprovalDecision.APPROVED, "human approval recorded")
        if human_approved is False:
            return ApprovalResult(ApprovalDecision.REJECTED, "human rejected repair")
        return ApprovalResult(ApprovalDecision.REQUIRED, "human approval required for elevated risk")

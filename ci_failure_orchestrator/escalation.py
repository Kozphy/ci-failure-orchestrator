from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .repair_proposal import RepairProposal


@dataclass(frozen=True)
class HumanEscalation:
    """First-class, explicit human escalation result.

    This is not a generic exception. It captures enough context for a reviewer
    to make an informed decision without re-deriving the incident state.
    """

    incident_id: str
    incident_type: str
    current_diagnosis: str
    repair_proposal: RepairProposal | None
    attempt_history: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    policy_reason: str
    verification_failures: tuple[str, ...]
    risk_level: str
    recommended_human_action: str
    escalated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    retry_budget_remaining: int = 0
    confidence: float = 0.0
    human_review_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "incident_type": self.incident_type,
            "current_diagnosis": self.current_diagnosis,
            "repair_proposal": (
                self.repair_proposal.to_dict() if self.repair_proposal else None
            ),
            "attempt_history": list(self.attempt_history),
            "evidence_refs": list(self.evidence_refs),
            "policy_reason": self.policy_reason,
            "verification_failures": list(self.verification_failures),
            "risk_level": self.risk_level,
            "recommended_human_action": self.recommended_human_action,
            "escalated_at": self.escalated_at,
            "retry_budget_remaining": self.retry_budget_remaining,
            "confidence": self.confidence,
            "human_review_required": self.human_review_required,
        }


def build_escalation(
*,
incident_id: str,
incident_type: str,
current_diagnosis: str,
policy_reason: str,
recommended_human_action: str,
repair_proposal: RepairProposal | None = None,
attempt_history: list[str] | tuple[str, ...] | None = None,
evidence_refs: list[str] | tuple[str, ...] | None = None,
verification_failures: list[str] | tuple[str, ...] | None = None,
risk_level: str = "high",
confidence: float = 0.0,
retry_budget_remaining: int = 0,
human_review_required: bool = True,
) -> HumanEscalation:
    """Construct a HumanEscalation without losing incident context."""

    return HumanEscalation(
        incident_id=incident_id,
        incident_type=incident_type,
        current_diagnosis=current_diagnosis,
        repair_proposal=repair_proposal,
        attempt_history=tuple(attempt_history or ()),
        evidence_refs=tuple(evidence_refs or ()),
        policy_reason=policy_reason,
        verification_failures=tuple(verification_failures or ()),
        risk_level=risk_level,
        recommended_human_action=recommended_human_action,
        confidence=confidence,
        retry_budget_remaining=retry_budget_remaining,
    )

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .repair_proposal import FORBIDDEN_ACTIONS as _PROPOSAL_FORBIDDEN_ACTIONS
from .repair_proposal import SUPPORTED_ACTIONS as _PROPOSAL_SUPPORTED_ACTIONS
from .repair_proposal import RepairProposal, RiskClass

# ---------------------------------------------------------------------------
# Repair-plan evaluator
# ---------------------------------------------------------------------------

FORBIDDEN_ACTIONS: frozenset[str] = _PROPOSAL_FORBIDDEN_ACTIONS
SUPPORTED_ACTIONS: frozenset[str] = _PROPOSAL_SUPPORTED_ACTIONS

@dataclass(frozen=True)
class RepairPlanEvaluation:
    """Independent evaluation of a single repair proposal."""

    proposal_valid: bool
    policy_safe: bool
    rollback_present: bool
    verification_present: bool
    before_state_captured: bool
    forbidden_action_detected: bool
    unsupported_action_detected: bool
    evidence_refs_valid: bool
    confirmation_requirement_correct: bool
    incident_action_mapping_correct: bool
    reasons: tuple[str, ...]

    @property
    def pass_(self) -> bool:
        return (
            self.proposal_valid
            and self.policy_safe
            and not self.forbidden_action_detected
            and not self.unsupported_action_detected
            and self.rollback_present
            and self.verification_present
            and self.evidence_refs_valid
            and self.incident_action_mapping_correct
            and self.confirmation_requirement_correct
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_valid": self.proposal_valid,
            "policy_safe": self.policy_safe,
            "rollback_present": self.rollback_present,
            "verification_present": self.verification_present,
            "before_state_captured": self.before_state_captured,
            "forbidden_action_detected": self.forbidden_action_detected,
            "unsupported_action_detected": self.unsupported_action_detected,
            "evidence_refs_valid": self.evidence_refs_valid,
            "confirmation_requirement_correct": self.confirmation_requirement_correct,
            "incident_action_mapping_correct": self.incident_action_mapping_correct,
            "reasons": list(self.reasons),
        }


class RepairPlanEvaluator:
    """Deterministic checks for a proposed repair."""

    def __init__(
        self,
        *,
        valid_incident_actions: dict[str, set[str]] | None = None,
        evidence_namespace: str = "repair",
    ) -> None:
        self.valid_incident_actions = valid_incident_actions or {
            "TYPE_ERROR": {"targeted_repair", "inspect"},
            "BUILD_ERROR": {"build_config_fix", "targeted_repair"},
            "NETWORK_ERROR": {"bounded_infra_retry", "route_reconcile", "dns_resolver_repair", "reset_proxy_configuration"},
            "DEPENDENCY_ERROR": {"dependency_reconcile", "safe_dependency_upgrade"},
            "TEST_ASSERTION": {"targeted_repair", "quarantine_test"},
            "FLAKY_TEST": {"quarantine_test"},
            "PACKAGE_ERROR": {"build_config_fix", "dependency_reconcile"},
            "DEPLOYMENT_ERROR": {"safe_dependency_upgrade", "inspect"},
            "SECURITY_ERROR": {"safe_dependency_upgrade", "inspect"},
            "RUNTIME_ERROR": {"targeted_repair", "bounded_infra_retry"},
            "UNKNOWN": {"inspect", "escalate"},
        }
        self.evidence_namespace = evidence_namespace

    def evaluate(self, proposal: RepairProposal | None) -> RepairPlanEvaluation:
        if proposal is None:
            return RepairPlanEvaluation(
                proposal_valid=False,
                policy_safe=False,
                rollback_present=False,
                verification_present=False,
                before_state_captured=False,
                forbidden_action_detected=False,
                unsupported_action_detected=True,
                evidence_refs_valid=False,
                confirmation_requirement_correct=False,
                incident_action_mapping_correct=False,
                reasons=("no_proposal",),
            )

        reasons: list[str] = []

        if not proposal.hypothesis:
            reasons.append("missing_hypothesis")
        if proposal.confidence < 0.0 or proposal.confidence > 1.0:
            reasons.append("invalid_confidence")
        if not proposal.evidence_refs:
            reasons.append("missing_evidence_refs")
        if not proposal.limitations:
            reasons.append("missing_limitations")
        if not proposal.rollback_strategy:
            reasons.append("missing_rollback")
        if not proposal.verification_plan:
            reasons.append("missing_verification_plan")

        forbidden = proposal.candidate_action in FORBIDDEN_ACTIONS
        unsupported = not (proposal.candidate_action in SUPPORTED_ACTIONS)

        valid_mapping = self._valid_incident_action(proposal)

        evidence_valid = all(
            isinstance(ref, str) and ref and ref.startswith(self.evidence_namespace + ":")
            for ref in proposal.evidence_refs
        )

        confirmation_correct = (
            proposal.confirmation_required
            if proposal.risk_class.value in {"high", "critical"}
            else (not proposal.confirmation_required or proposal.confirmation_required is False)
        ) or (proposal.confirmation_required is True)

        return RepairPlanEvaluation(
            proposal_valid=not reasons,
            policy_safe=not forbidden and not unsupported,
            rollback_present=bool(proposal.rollback_strategy),
            verification_present=bool(proposal.verification_plan),
            before_state_captured=bool(proposal.before_state_required),
            forbidden_action_detected=forbidden,
            unsupported_action_detected=unsupported,
            evidence_refs_valid=evidence_valid,
            confirmation_requirement_correct=confirmation_correct,
            incident_action_mapping_correct=valid_mapping,
            reasons=tuple(reasons),
        )

    def _valid_incident_action(self, proposal: RepairProposal) -> bool:
        allowed = self.valid_incident_actions.get(proposal.incident_type)
        if not allowed:
            return False
        return proposal.candidate_action in allowed

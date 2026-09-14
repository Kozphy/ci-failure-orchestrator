from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

# ---------------------------------------------------------------------------
# Incident / proposal identifiers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IncidentRef:
    incident_id: str
    probe_id: str | None = None


@dataclass(frozen=True)
class ProposalRef:
    proposal_id: str
    incident_id: str
    parent_proposal_id: str | None = None


# ---------------------------------------------------------------------------
# Risk class
# ---------------------------------------------------------------------------

class RiskClass(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Repair proposal (model = hypothesis only)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RepairProposal:
    """A structured repair *proposal* produced by a diagnosis/planning layer.

    The model proposes. The deterministic harness verifies, gates, and may
    eventually execute through controlled remediation paths only.
    """

    proposal_id: str
    incident_id: str
    incident_type: str
    hypothesis: str
    evidence_refs: tuple[str, ...]
    candidate_action: str
    risk_class: RiskClass
    before_state_required: bool
    preview_required: bool
    confirmation_required: bool
    rollback_strategy: str
    verification_plan: tuple[str, ...]
    limitations: tuple[str, ...]
    confidence: float = 0.0
    human_review_required: bool = False
    model: str | None = None
    parent_proposal_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "incident_id": self.incident_id,
            "incident_type": self.incident_type,
            "confidence": self.confidence,
            "hypothesis": self.hypothesis,
            "evidence_refs": list(self.evidence_refs),
            "candidate_action": self.candidate_action,
            "risk_class": self.risk_class.value,
            "before_state_required": self.before_state_required,
            "preview_required": self.preview_required,
            "confirmation_required": self.confirmation_required,
            "rollback_strategy": self.rollback_strategy,
            "verification_plan": list(self.verification_plan),
            "limitations": list(self.limitations),
            "human_review_required": self.human_review_required,
            "model": self.model,
            "parent_proposal_id": self.parent_proposal_id,
        }


def repair_proposal_roundtrip(data: dict) -> RepairProposal:
    """Rebuild a RepairProposal from its serialized form."""
    return build_proposal(
        incident_id=data.get("incident_id", ""),
        incident_type=data.get("incident_type", ""),
        hypothesis=data.get("hypothesis", ""),
        evidence_refs=list(data.get("evidence_refs", []) or ()),
        candidate_action=data.get("candidate_action", "inspect"),
        risk_class=data.get("risk_class", "low"),
        rollback_strategy=data.get("rollback_strategy", "revert_patch"),
        verification_plan=list(data.get("verification_plan", []) or ()),
        limitations=list(data.get("limitations", []) or ()),
        confidence=float(data.get("confidence", 0.0)),
        human_review_required=bool(data.get("human_review_required", False)),
    )

# ---------------------------------------------------------------------------
# Action sets
# ---------------------------------------------------------------------------

FORBIDDEN_ACTIONS = frozenset({
    "disable_security_scanner",
    "delete_failing_tests",
    "disable_required_checks",
    "add_continue_on_error_to_hide_failure",
    "lower_coverage_threshold_without_policy_approval",
    "expose_or_modify_secrets",
    "force_merge",
    "reset_firewall",
    "disable_adapter",
    "kill_process",
    "mutate_registry_directly",
    "run_arbitrary_powershell",
    "reset_tls_stack",
    "bypass_policy_gate",
})

SUPPORTED_ACTIONS = frozenset({
    "inspect",
    "quarantine_test",
    "targeted_repair",
    "dependency_reconcile",
    "build_config_fix",
    "safe_dependency_upgrade",
    "bounded_infra_retry",
    "reset_proxy_configuration",
    "renew_tls_configuration",
    "dns_resolver_repair",
    "route_reconcile",
    "escalate",
})


KNOWN_ACTIONS = SUPPORTED_ACTIONS | FORBIDDEN_ACTIONS

class ProposalValidationError(ValueError):
    """Raised when a proposed repair is malformed or unsafe at the boundary."""


def build_proposal(
    *,
    incident_id: str,
    incident_type: str,
    hypothesis: str,
    evidence_refs: list[str] | tuple[str, ...] | None,
    candidate_action: str,
    risk_class: RiskClass | str,
    rollback_strategy: str,
    verification_plan: list[str] | tuple[str, ...],
    limitations: list[str] | tuple[str, ...],
    confidence: float = 0.0,
    before_state_required: bool | None = None,
    preview_required: bool | None = None,
    confirmation_required: bool | None = None,
    human_review_required: bool | None = None,
    model: str | None = None,
    proposal_id: str | None = None,
    parent_proposal_id: str | None = None,
) -> RepairProposal:
    """Validate shape AND unsafe content; fail closed."""

    risk_class = RiskClass(risk_class)

    if not proposal_id:
        proposal_id = uuid4().hex

    if not incident_id:
        raise ProposalValidationError("incident_id is required")

    if not incident_type:
        raise ProposalValidationError("incident_type is required")

    if not hypothesis:
        raise ProposalValidationError("hypothesis is required")

    if candidate_action not in KNOWN_ACTIONS:
        raise ProposalValidationError(
            f"unsupported candidate_action: {candidate_action!r}"
        )

    if candidate_action in FORBIDDEN_ACTIONS:
        raise ProposalValidationError(
            f"forbidden candidate_action: {candidate_action!r}"
        )

    if not isinstance(verification_plan, (list, tuple)) or not verification_plan:
        raise ProposalValidationError("verification_plan must be non-empty")

    if not isinstance(limitations, (list, tuple)):
        raise ProposalValidationError("limitations must be a sequence")

    if not rollback_strategy:
        raise ProposalValidationError("rollback_strategy must be non-empty")

    if not (0.0 <= confidence <= 1.0):
        raise ProposalValidationError(f"confidence out of range: {confidence}")

    # Weak-evidence heuristic: if confidence is low and there are no stated
    # limitations, the proposal is untrustworthy.
    if confidence <= 0.49 and not limitations:
        human_review_required = True

    if human_review_required is None:
        human_review_required = risk_class in {RiskClass.HIGH, RiskClass.CRITICAL}

    # Default mutability flags from risk class if not supplied explicitly.
    if before_state_required is None:
        before_state_required = risk_class in {RiskClass.MEDIUM, RiskClass.HIGH, RiskClass.CRITICAL}
    if preview_required is None:
        preview_required = risk_class in {RiskClass.MEDIUM, RiskClass.HIGH, RiskClass.CRITICAL}
    if confirmation_required is None:
        confirmation_required = risk_class in {RiskClass.HIGH, RiskClass.CRITICAL}

    return RepairProposal(
        proposal_id=proposal_id,
        incident_id=incident_id,
        incident_type=incident_type,
        hypothesis=hypothesis,
        evidence_refs=tuple(evidence_refs or ()),
        candidate_action=candidate_action,
        risk_class=risk_class,
        before_state_required=before_state_required,
        preview_required=preview_required,
        confirmation_required=confirmation_required,
        rollback_strategy=rollback_strategy,
        verification_plan=tuple(verification_plan),
        limitations=tuple(limitations),
        confidence=confidence,
        human_review_required=human_review_required,
        model=model,
        parent_proposal_id=parent_proposal_id,
    )


def repair_proposal_roundtrip(data: dict) -> RepairProposal:
    """Rebuild a RepairProposal from its serialized form without re-running
    full validation. Used by tests and audit round-trips where the payload is
    already known-good.
    """
    return RepairProposal(
        proposal_id=data.get("proposal_id", ""),
        incident_id=data.get("incident_id", ""),
        incident_type=data.get("incident_type", ""),
        hypothesis=data.get("hypothesis", ""),
        evidence_refs=tuple(data.get("evidence_refs", []) or ()),
        candidate_action=data.get("candidate_action", "inspect"),
        risk_class=RiskClass(data.get("risk_class", "low")),
        before_state_required=bool(data.get("before_state_required", False)),
        preview_required=bool(data.get("preview_required", False)),
        confirmation_required=bool(data.get("confirmation_required", False)),
        rollback_strategy=data.get("rollback_strategy", "revert_patch"),
        verification_plan=tuple(data.get("verification_plan", []) or ()),
        limitations=tuple(data.get("limitations", []) or ()),
        confidence=float(data.get("confidence", 0.0)),
        human_review_required=bool(data.get("human_review_required", False)),
        model=data.get("model"),
        parent_proposal_id=data.get("parent_proposal_id"),
    )

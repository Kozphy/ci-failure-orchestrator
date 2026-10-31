from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .repair_proposal import RepairProposal

# ---------------------------------------------------------------------------
# Dispositions
# ---------------------------------------------------------------------------

class ProposalDisposition(str, Enum):
    """Centralized policy decision for one repair proposal."""

    PREVIEW_READY = "preview_ready"
    AWAIT_CONFIRMATION = "await_confirmation"
    BLOCKED = "blocked"
    ESCALATE = "escalate"


# ---------------------------------------------------------------------------
# Policy context
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProposalPolicyContext:
    """Inputs to the proposal policy gate."""

    proposal: RepairProposal
    evidence_level: int = 1  # 0 = none, 1 = minimal, 2 = structured, 3 = strong
    human_review_required: bool = False
    protected_operation: bool = False


# ---------------------------------------------------------------------------
# Proposal policy gate
# ---------------------------------------------------------------------------

class ProposalPolicyGate:
    """Fail-closed policy decision for a single repair proposal.

    Every mutable proposal should pass here before preview, sandbox, or live
    execution. The gate intentionally cannot be bypassed by model confidence.
    """

    def decide(self, ctx: ProposalPolicyContext) -> ProposalDisposition:
        proposal = ctx.proposal

        if not proposal:
            return ProposalDisposition.ESCALATE

        if ctx.protected_operation:
            return ProposalDisposition.BLOCKED

        if proposal.candidate_action not in _SUPPORTED_MUTABLE_ACTIONS:
            return ProposalDisposition.BLOCKED

        # Fail closed for weak evidence before any human-review shortcut.
        if proposal.confidence <= 0.49:
            return ProposalDisposition.ESCALATE

        if not proposal.rollback_strategy:
            return ProposalDisposition.ESCALATE

        if not proposal.verification_plan:
            return ProposalDisposition.ESCALATE

        # Note: human_review_required already triggers AWAIT_CONFIRMATION even for
        # high-confidence proposals; low confidence escalates above.

        if ctx.human_review_required or proposal.human_review_required:
            return ProposalDisposition.AWAIT_CONFIRMATION

        if proposal.risk_class.value in {"high", "critical"}:
            return ProposalDisposition.AWAIT_CONFIRMATION

        return ProposalDisposition.PREVIEW_READY


_SUPPORTED_MUTABLE_ACTIONS = frozenset({
    "targeted_repair",
    "dependency_reconcile",
    "build_config_fix",
    "safe_dependency_upgrade",
    "bounded_infra_retry",
    "reset_proxy_configuration",
    "renew_tls_configuration",
    "dns_resolver_repair",
    "route_reconcile",
})

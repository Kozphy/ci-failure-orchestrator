from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import perf_counter
from typing import Any

from .escalation import HumanEscalation, build_escalation
from .model_client import FixtureModelClient, StructuredDiagnosis, StructuredModelClient, validate_and_build_diagnosis
from .repair_plan_evaluator import RepairPlanEvaluator, RepairPlanEvaluation
from .repair_proposal import FORBIDDEN_ACTIONS, RiskClass, build_proposal, ProposalValidationError, RepairProposal as RepairProposalTyped
from .proposal_policy import ProposalDisposition, ProposalPolicyContext, ProposalPolicyGate
from .verification import VerificationStep, plan_verification


class AgentStep(str, Enum):
    EVIDENCE = "evidence"
    CLASSIFY = "classify"
    LLM_DIAGNOSIS = "llm_diagnosis"
    PROPOSAL = "proposal"
    POLICY = "policy"
    PREVIEW = "preview"
    VERIFY = "verify"
    RETRY = "retry"
    ESCALATE = "escalate"
    AUDIT = "audit"


@dataclass(frozen=True)
class AgentStepTrace:
    step: AgentStep
    started_at: str
    ended_at: str | None = None
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRunResult:
    incident_id: str
    disposition: str
    proposal_id: str | None
    policy_disposition: ProposalDisposition | None
    diagnosis: StructuredDiagnosis | None
    proposal: "RepairProposalTyped" | None
    verification_plan: list[str]
    attempt_count: int
    retry_budget_remaining: int
    escalation: HumanEscalation | None
    steps: tuple[AgentStepTrace, ...]
    audit_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "disposition": self.disposition,
            "proposal_id": self.proposal_id,
            "policy_disposition": (
                self.policy_disposition.value if self.policy_disposition else None
            ),
            "diagnosis": (
                {
                    "incident_type": self.diagnosis.incident_type,
                    "confidence": self.diagnosis.confidence,
                    "hypothesis": self.diagnosis.hypothesis,
                    "evidence_refs": list(self.diagnosis.evidence_refs),
                    "limitations": list(self.diagnosis.limitations),
                    "recommended_action": self.diagnosis.recommended_action,
                    "human_review_required": self.diagnosis.human_review_required,
                    "model": self.diagnosis.model,
                }
                if self.diagnosis
                else None
            ),
            "proposal": self.proposal.to_dict() if self.proposal else None,
            "verification_plan": self.verification_plan,
            "attempt_count": self.attempt_count,
            "retry_budget_remaining": self.retry_budget_remaining,
            "escalation": self.escalation.to_dict() if self.escalation else None,
            "steps": [s.__dict__ for s in self.steps],
            "audit_path": self.audit_path,
        }


# Import later to avoid circular issues at module level in this demo-grade
# harness; real code would separate type and runtime cleanly.
from .repair_proposal import RepairProposal as RepairProposalTyped


class BoundedRepairAgentHarness:
    """Agentic harness that keeps the LLM as a proposal layer only.

    Flow:

        evidence
        ↓
        classify
        ↓
        LLM diagnosis
        ↓
        repair proposal
        ↓
        policy gate
        ↓
        preview / sandbox
        ↓
        verification plan
        ↓
        retry / escalate
        ↓
        audit
    """

    def __init__(
        self,
        *,
        model: StructuredModelClient,
        max_attempts: int = 3,
        evidence_namespace: str = "repair",
        audit_path: str | None = None,
    ) -> None:
        self.model = model
        self.max_attempts = max_attempts
        self.evidence_namespace = evidence_namespace
        self.audit_path = audit_path
        self._steps: list[AgentStepTrace] = []

    def run(self, incident: dict[str, Any]) -> AgentRunResult:
        incident_id = incident.get("incident_id") or "INC-UNKNOWN"
        self._steps = []
        attempt_count = 0
        retry_budget = self.max_attempts

        diagnosis = self._diagnose(incident_id, incident)
        if diagnosis is None:
            return self._final(
                incident_id,
                disposition="ESCALATE",
                diagnosis=None,
                proposal=None,
                policy_disposition=None,
                attempt_count=attempt_count,
                retry_budget_remaining=retry_budget,
                escalation=self._no_diagnosis_escalation(incident_id, incident),
            )

        proposal = self._propose(diagnosis, incident)
        if proposal is None:
            return self._final(
                incident_id,
                disposition="ESCALATE",
                diagnosis=diagnosis,
                proposal=None,
                policy_disposition=ProposalDisposition.ESCALATE,
                attempt_count=attempt_count,
                retry_budget_remaining=retry_budget,
                escalation=self._invalid_proposal_escalation(incident_id, diagnosis),
            )

        policy = self._policy(proposal)
        if policy is ProposalDisposition.ESCALATE:
            attempt_count += 1
            retry_budget = max(retry_budget - 1, 0)
            esc = build_escalation(
                incident_id=incident_id,
                incident_type=proposal.incident_type,
                current_diagnosis=diagnosis.hypothesis,
                policy_reason="policy_escalated",
                recommended_human_action="review diagnosis, evidence, and limitations before any remediation",
                repair_proposal=proposal,
                attempt_history=[f"attempt={attempt_count}:policy_escalated"],
                evidence_refs=list(proposal.evidence_refs),
                verification_failures=(),
                risk_level=proposal.risk_class.value,
                confidence=diagnosis.confidence,
                retry_budget_remaining=retry_budget,
            )
            return self._final(
                incident_id,
                disposition="ESCALATE",
                diagnosis=diagnosis,
                proposal=proposal,
                policy_disposition=ProposalDisposition.ESCALATE,
                attempt_count=attempt_count,
                retry_budget_remaining=retry_budget,
                escalation=esc,
            )

        if policy is ProposalDisposition.BLOCKED:
            attempt_count += 1
            retry_budget = max(retry_budget - 1, 0)
            esc = build_escalation(
                incident_id=incident_id,
                incident_type=proposal.incident_type,
                current_diagnosis=diagnosis.hypothesis,
                policy_reason="proposal_blocked_by_policy",
                recommended_human_action="do not apply model-suggested action; inspect evidence manually",
                repair_proposal=proposal,
                attempt_history=[f"attempt={attempt_count}:blocked"],
                evidence_refs=list(proposal.evidence_refs),
                verification_failures=(),
                risk_level=proposal.risk_class.value,
                confidence=diagnosis.confidence,
                retry_budget_remaining=retry_budget,
            )
            return self._final(
                incident_id,
                disposition="BLOCKED",
                diagnosis=diagnosis,
                proposal=proposal,
                policy_disposition=ProposalDisposition.BLOCKED,
                attempt_count=attempt_count,
                retry_budget_remaining=retry_budget,
                escalation=esc,
            )

        # Remaining paths: PREVIEW_READY / AWAIT_CONFIRMATION
        verification_plan = self._verification_plan(proposal, incident)
        attempt_count += 1
        retry_budget = max(retry_budget - 1, 0)

        if policy is ProposalDisposition.AWAIT_CONFIRMATION:
            esc = build_escalation(
                incident_id=incident_id,
                incident_type=proposal.incident_type,
                current_diagnosis=diagnosis.hypothesis,
                policy_reason="confirmation_required_by_policy",
                recommended_human_action="approve or reject the proposed repair after reviewing the preview and verification plan",
                repair_proposal=proposal,
                attempt_history=[f"attempt={attempt_count}:awaiting_confirmation"],
                evidence_refs=list(proposal.evidence_refs),
                verification_failures=(),
                risk_level=proposal.risk_class.value,
                confidence=diagnosis.confidence,
                retry_budget_remaining=retry_budget,
            )
            return self._final(
                incident_id,
                disposition="AWAIT_CONFIRMATION",
                diagnosis=diagnosis,
                proposal=proposal,
                policy_disposition=ProposalDisposition.AWAIT_CONFIRMATION,
                attempt_count=attempt_count,
                retry_budget_remaining=retry_budget,
                escalation=esc,
                verification_plan=verification_plan,
            )

        # PREVIEW_READY: we still stop before any live mutation.
        return self._final(
            incident_id,
            disposition="PREVIEW_READY",
            diagnosis=diagnosis,
            proposal=proposal,
            policy_disposition=ProposalDisposition.PREVIEW_READY,
            attempt_count=attempt_count,
            retry_budget_remaining=retry_budget,
            escalation=None,
            verification_plan=verification_plan,
        )

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _diagnose(self, incident_id: str, incident: dict[str, Any]) -> StructuredDiagnosis | None:
        probe = incident.get("probe_id") or "PROBE-UNKNOWN"
        start = perf_counter()
        try:
            payload = {
                "incident_id": incident_id,
                "probe_id": probe,
                "evidence_summary": incident.get("evidence_summary", ""),
                "failure_message": incident.get("failure_message", ""),
            }
            raw = self.model.complete(payload)
            diagnosis = validate_and_build_diagnosis(
                raw,
                model=self.model.__class__.__name__,
            )
            self._record(AgentStep.LLM_DIAGNOSIS, start, "diagnosis_parsed", diagnosis.to_dict())
            return diagnosis
        except Exception as exc:
            self._record(AgentStep.LLM_DIAGNOSIS, start, "diagnosis_invalid", {"error": str(exc)})
            return None

    def _propose(
        self, diagnosis: StructuredDiagnosis, incident: dict[str, Any]
    ) -> RepairProposalTyped | None:
        start = perf_counter()
        try:
            # Map model recommended_action into a concrete candidate_action where
            # possible; the harness never trusts the model for authority.
            candidate_action = self._map_action(diagnosis.recommended_action, diagnosis.incident_type)

            # Forbidden actions are blocked at the proposal layer before any policy
            # or preview path is entered.
            if candidate_action in FORBIDDEN_ACTIONS:
                raise ProposalValidationError(
                    f"forbidden candidate_action: {candidate_action!r}"
                )

            verification_plan = [
                f"{self.evidence_namespace}:targeted_check",
                f"{self.evidence_namespace}:regression_check",
            ]
            proposal = build_proposal(
                incident_id=diagnosis.incident_type if False else incident.get("incident_id") or "INC-UNKNOWN",
                incident_type=diagnosis.incident_type,
                hypothesis=diagnosis.hypothesis,
                evidence_refs=list(diagnosis.evidence_refs),
                candidate_action=candidate_action,
                risk_class=self._risk_class_from_confidence_and_action(diagnosis.confidence, candidate_action),
                rollback_strategy=self._default_rollback(candidate_action),
                verification_plan=verification_plan,
                limitations=list(diagnosis.limitations),
                confidence=diagnosis.confidence,
                human_review_required=diagnosis.human_review_required,
                model=diagnosis.model,
            )
            self._record(AgentStep.PROPOSAL, start, "proposal_built", proposal.to_dict())
            return proposal
        except ProposalValidationError as exc:
            self._record(AgentStep.PROPOSAL, start, "proposal_invalid", {"error": str(exc)})
            return None

    def _policy(self, proposal: RepairProposalTyped) -> ProposalDisposition:
        start = perf_counter()
        ctx = ProposalPolicyContext(
            proposal=proposal,
            evidence_level=2,
            human_review_required=proposal.human_review_required,
            protected_operation=False,
        )
        disposition = ProposalPolicyGate().decide(ctx)
        self._record(AgentStep.POLICY, start, f"policy_disposition={disposition.value}", {
            "proposal_id": proposal.proposal_id,
            "incident_type": proposal.incident_type,
            "candidate_action": proposal.candidate_action,
            "risk_class": proposal.risk_class.value,
            "confidence": proposal.confidence,
            "human_review_required": proposal.human_review_required,
            "disposition": disposition.value,
        })
        return disposition

    def _verification_plan(
        self, proposal: RepairProposalTyped, incident: dict[str, Any]
    ) -> list[str]:
        start = perf_counter()
        plan = [
            f"{self.evidence_namespace}:before_state_capture",
            f"{self.evidence_namespace}:targeted_check",
            f"{self.evidence_namespace}:regression_check",
        ]
        self._record(AgentStep.VERIFY, start, "verification_plan_ready", {"steps": plan})
        return plan

    def _map_action(self, recommended: str, incident_type: str) -> str:
        # Known safe actions pass through; unknown model recommendations
        # default to the safe "inspect" action. Forbidden actions are NOT
        # mapped here by design — they are caught by the forbidden check later
        # so the harness can escalate with a clear reason.
        mapping = {
            "inspect": "inspect",
            "quarantine_test": "quarantine_test",
            "targeted_repair": "targeted_repair",
            "dependency_reconcile": "dependency_reconcile",
            "build_config_fix": "build_config_fix",
            "safe_dependency_upgrade": "safe_dependency_upgrade",
            "bounded_infra_retry": "bounded_infra_retry",
            "reset_proxy_configuration": "reset_proxy_configuration",
            "renew_tls_configuration": "renew_tls_configuration",
            "dns_resolver_repair": "dns_resolver_repair",
            "route_reconcile": "route_reconcile",
            "escalate": "escalate",
        }
        if recommended in mapping:
            return mapping[recommended]
        if recommended in KNOWN_ACTIONS:
            # Model recommended a known action (possibly forbidden). Pass it
            # through so the forbidden check below can escalate cleanly.
            return recommended
        return "inspect"

    def _risk_class_from_confidence_and_action(self, confidence: float, action: str) -> RiskClass:
        if confidence <= 0.49:
            return RiskClass.HIGH
        if action in {"bounded_infra_retry", "reset_proxy_configuration", "renew_tls_configuration", "dns_resolver_repair", "route_reconcile"}:
            return RiskClass.MEDIUM
        if action in {"safe_dependency_upgrade", "dependency_reconcile"}:
            return RiskClass.MEDIUM
        if action in {"targeted_repair", "build_config_fix"}:
            return RiskClass.LOW
        return RiskClass.MEDIUM

    def _default_rollback(self, action: str) -> str:
        mapping = {
            "inspect": "no_change_required",
            "quarantine_test": "un quarantine_test",
            "targeted_repair": "revert_patch",
            "dependency_reconcile": "restore_previous_lockfile",
            "build_config_fix": "revert_build_config",
            "safe_dependency_upgrade": "revert_dependency_upgrade",
            "bounded_infra_retry": "restore_previous_infra_state",
            "reset_proxy_configuration": "restore_previous_proxy_config",
            "renew_tls_configuration": "restore_previous_tls_config",
            "dns_resolver_repair": "restore_previous_dns_config",
            "route_reconcile": "restore_previous_route_config",
            "escalate": "no_change_required",
        }
        return mapping.get(action, "revert_patch")

    # ------------------------------------------------------------------

    def _record(self, step: AgentStep, start: float, summary: str, payload: dict[str, Any] | None = None) -> None:
        ended = perf_counter()
        self._steps.append(
            AgentStepTrace(
                step=step,
                started_at=self._approx_iso(start),
                ended_at=self._approx_iso(ended),
                summary=summary,
                payload=payload or {},
            )
        )

    @staticmethod
    def _approx_iso(seconds: float) -> str:
        # Deterministic-friendly fake ISO using a fixed epoch offset for tests.
        from datetime import datetime, timezone, timedelta
        return (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()

    def _final(
        self,
        incident_id: str,
        disposition: str,
        diagnosis: StructuredDiagnosis | None,
        proposal: RepairProposalTyped | None,
        policy_disposition: ProposalDisposition | None,
        attempt_count: int,
        retry_budget_remaining: int,
        escalation: HumanEscalation | None,
        verification_plan: list[str] | None = None,
    ) -> AgentRunResult:
        self._record(AgentStep.AUDIT, perf_counter(), f"run_complete:disposition={disposition}", {
            "incident_id": incident_id,
            "disposition": disposition,
            "proposal_id": proposal.proposal_id if proposal else None,
            "policy_disposition": policy_disposition.value if policy_disposition else None,
        })
        return AgentRunResult(
            incident_id=incident_id,
            disposition=disposition,
            proposal_id=proposal.proposal_id if proposal else None,
            policy_disposition=policy_disposition,
            diagnosis=diagnosis,
            proposal=proposal,
            verification_plan=verification_plan or [],
            attempt_count=attempt_count,
            retry_budget_remaining=retry_budget_remaining,
            escalation=escalation,
            steps=tuple(self._steps),
            audit_path=self.audit_path,
        )

    def _no_diagnosis_escalation(self, incident_id: str, incident: dict[str, Any]) -> HumanEscalation:
        return build_escalation(
            incident_id=incident_id,
            incident_type=incident.get("failure_message", "") or "UNKNOWN",
            current_diagnosis="model output could not be validated",
            policy_reason="llm_diagnosis_validation_failed",
            recommended_human_action="review raw evidence and classify manually before any repair proposal",
            evidence_refs=[],
            verification_failures=("diagnosis_validation_failed",),
            risk_level="high",
        )

    def _invalid_proposal_escalation(
        self, incident_id: str, diagnosis: StructuredDiagnosis
    ) -> HumanEscalation:
        return build_escalation(
            incident_id=incident_id,
            incident_type=diagnosis.incident_type,
            current_diagnosis=diagnosis.hypothesis,
            policy_reason="proposal_validation_failed",
            recommended_human_action="reject model proposal; remediation must go through deterministic policy path",
            evidence_refs=list(diagnosis.evidence_refs),
            verification_failures=("proposal_validation_failed",),
            risk_level="high",
            confidence=diagnosis.confidence,
        )

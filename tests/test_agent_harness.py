from __future__ import annotations

from ci_failure_orchestrator.model_client import (
    FixtureModelClient,
    StructuredDiagnosis,
    validate_and_build_diagnosis,
)
from ci_failure_orchestrator.repair_proposal import (
    FORBIDDEN_ACTIONS,
    SUPPORTED_ACTIONS,
    RiskClass,
    RepairProposal,
    build_proposal,
    repair_proposal_roundtrip,
    ProposalValidationError,
)
from ci_failure_orchestrator.proposal_policy import ProposalDisposition, ProposalPolicyContext, ProposalPolicyGate
from ci_failure_orchestrator.repair_plan_evaluator import RepairPlanEvaluator, RepairPlanEvaluation
from ci_failure_orchestrator.escalation import HumanEscalation, build_escalation
from ci_failure_orchestrator.agent_harness import (
    AgentStep,
    BoundedRepairAgentHarness,
    FixtureModelClient as HarnessFixtureClient,
)

import pytest


# ---------------------------------------------------------------------------
# model_client
# ---------------------------------------------------------------------------

VALID_DIAGNOSIS_PAYLOAD = {
    "incident_type": "NETWORK_ERROR",
    "confidence": 0.82,
    "hypothesis": "proxy drift",
    "evidence_refs": ["repair:probe:WININET-001"],
    "limitations": ["single observation window"],
    "recommended_action": "targeted_repair",
}


def test_valid_structured_output():
    diag = validate_and_build_diagnosis(VALID_DIAGNOSIS_PAYLOAD, model="structured-proposal-v1")
    assert diag.incident_type == "NETWORK_ERROR"
    assert diag.confidence == 0.82
    assert diag.human_review_required is False


def test_low_confidence_requires_human_review():
    payload = {
        "incident_type": "NETWORK_ERROR",
        "confidence": 0.30,
        "hypothesis": "maybe proxy drift",
        "evidence_refs": [],
        "limitations": [],
        "recommended_action": "targeted_repair",
    }
    diag = validate_and_build_diagnosis(payload, model="structured-proposal-v1")
    assert diag.confidence == 0.30
    assert diag.human_review_required is True


def test_unknown_incident_type_fails_closed():
    payload = {
        "incident_type": "BOGUS_ERROR",
        "confidence": 0.82,
        "hypothesis": "unknown",
        "evidence_refs": [],
        "limitations": [],
        "recommended_action": "targeted_repair",
    }
    with pytest.raises(Exception):
        validate_and_build_diagnosis(payload, model="structured-proposal-v1")


def test_unsupported_recommended_action_fails_closed():
    payload = {
        **VALID_DIAGNOSIS_PAYLOAD,
        "recommended_action": "run_who_knows",
    }
    with pytest.raises(Exception):
        validate_and_build_diagnosis(payload, model="structured-proposal-v1")


def test_confidence_out_of_range_fails_closed():
    payload = {
        **VALID_DIAGNOSIS_PAYLOAD,
        "confidence": 1.3,
    }
    with pytest.raises(Exception):
        validate_and_build_diagnosis(payload, model="structured-proposal-v1")


def test_missing_limitations_weak_evidence_fails_closed_via_human_review():
    payload = {
        "incident_type": "NETWORK_ERROR",
        "confidence": 0.30,
        "hypothesis": "proxy drift",
        "evidence_refs": ["repair:probe:WININET-001"],
        "limitations": [],
        "recommended_action": "targeted_repair",
    }
    diag = validate_and_build_diagnosis(payload, model="structured-proposal-v1")
    assert diag.human_review_required is True


def test_fixture_model_client_returns_payload():
    model = FixtureModelClient(VALID_DIAGNOSIS_PAYLOAD, model="fixture-v1")
    raw = model.complete(payload={"ignore": True})
    assert raw is not VALID_DIAGNOSIS_PAYLOAD
    assert raw["incident_type"] == "NETWORK_ERROR"


# ---------------------------------------------------------------------------
# repair_proposal
# ---------------------------------------------------------------------------

def test_valid_proposal():
    prop = build_proposal(
        incident_id="INC-001",
        incident_type="NETWORK_ERROR",
        hypothesis="proxy drift",
        evidence_refs=["repair:probe:WININET-001"],
        candidate_action="reset_proxy_configuration",
        risk_class="medium",
        rollback_strategy="restore_previous_proxy_config",
        verification_plan=["repair:targeted_check", "repair:regression_check"],
        limitations=["single window"],
        confidence=0.82,
    )
    assert prop.proposal_id
    assert prop.candidate_action == "reset_proxy_configuration"
    assert prop.risk_class == RiskClass.MEDIUM
    assert prop.before_state_required is True
    assert prop.preview_required is True
    assert prop.confirmation_required is False


def test_forbidden_action_fails_closed():
    with pytest.raises(ProposalValidationError, match="forbidden"):
        build_proposal(
            incident_id="INC-001",
            incident_type="NETWORK_ERROR",
            hypothesis="reset firewall",
            evidence_refs=["repair:probe:WININET-001"],
            candidate_action="reset_firewall",
            risk_class="high",
            rollback_strategy="restore_firewall",
            verification_plan=["repair:targeted_check"],
            limitations=["single window"],
        )


def test_missing_rollback_fails_closed():
    with pytest.raises(ProposalValidationError, match="rollback_strategy must be non-empty"):
        build_proposal(
            incident_id="INC-001",
            incident_type="NETWORK_ERROR",
            hypothesis="proxy drift",
            evidence_refs=["repair:probe:WININET-001"],
            candidate_action="targeted_repair",
            risk_class="low",
            rollback_strategy="",
            verification_plan=["repair:targeted_check"],
            limitations=["single window"],
        )


def test_missing_verification_fails_closed():
    with pytest.raises(ProposalValidationError, match="verification_plan must be non-empty"):
        build_proposal(
            incident_id="INC-001",
            incident_type="NETWORK_ERROR",
            hypothesis="proxy drift",
            evidence_refs=["repair:probe:WININET-001"],
            candidate_action="targeted_repair",
            risk_class="low",
            rollback_strategy="revert_patch",
            verification_plan=[],
            limitations=["single window"],
        )


def test_invalid_confidence_fails_closed():
    with pytest.raises(Exception):
        build_proposal(
            incident_id="INC-001",
            incident_type="NETWORK_ERROR",
            hypothesis="proxy drift",
            evidence_refs=["repair:probe:WININET-001"],
            candidate_action="targeted_repair",
            risk_class="low",
            rollback_strategy="revert_patch",
            verification_plan=["repair:targeted_check"],
            limitations=["single window"],
            confidence=1.5,
        )


def test_unsupported_action_fails_closed():
    with pytest.raises(Exception):
        build_proposal(
            incident_id="INC-001",
            incident_type="NETWORK_ERROR",
            hypothesis="proxy drift",
            evidence_refs=["repair:probe:WININET-001"],
            candidate_action="run_powershell",
            risk_class="low",
            rollback_strategy="revert_patch",
            verification_plan=["repair:targeted_check"],
            limitations=["single window"],
        )


def test_proposal_roundtrip() -> None:
    prop = build_proposal(
        incident_id="INC-001",
        incident_type="NETWORK_ERROR",
        hypothesis="proxy drift",
        evidence_refs=["repair:probe:WININET-001"],
        candidate_action="reset_proxy_configuration",
        risk_class="medium",
        rollback_strategy="restore_previous_proxy_config",
        verification_plan=["repair:targeted_check"],
        limitations=["single window"],
        confidence=0.82,
        human_review_required=True,
    )
    rebuilt = repair_proposal_roundtrip(prop.to_dict())
    assert rebuilt.proposal_id == prop.proposal_id
    assert rebuilt.human_review_required is True
    assert rebuilt.parent_proposal_id == prop.parent_proposal_id


# ---------------------------------------------------------------------------
# proposal_policy
# ---------------------------------------------------------------------------

def test_policy_blocks_forbidden_action():
    """Demonstrate that an evaluator/gate layer detects a forbidden action that
    somehow bypassed the primary build_proposal boundary (defensive coverage)."""
    evaluator = RepairPlanEvaluator()
    prop = RepairProposal(
        proposal_id="P-001",
        incident_id="INC-001",
        incident_type="NETWORK_ERROR",
        hypothesis="proxy drift",
        evidence_refs=["repair:probe:WININET-001"],
        candidate_action="disable_security_scanner",
        risk_class=RiskClass.LOW,
        before_state_required=False,
        preview_required=False,
        confirmation_required=False,
        rollback_strategy="revert_patch",
        verification_plan=["repair:targeted_check"],
        limitations=["single window"],
        confidence=0.82,
    )
    result = evaluator.evaluate(prop)
    assert result.forbidden_action_detected is True
    assert result.pass_ is False


def test_policy_awaits_confirmation_for_high_risk():
    gate = ProposalPolicyGate()
    prop = build_proposal(
        incident_id="INC-001",
        incident_type="NETWORK_ERROR",
        hypothesis="proxy drift",
        evidence_refs=["repair:probe:WININET-001"],
        candidate_action="reset_proxy_configuration",
        risk_class="high",
        rollback_strategy="restore_previous_proxy_config",
        verification_plan=["repair:targeted_check"],
        limitations=["single window"],
        confidence=0.82,
    )
    ctx = ProposalPolicyContext(proposal=prop, protected_operation=False)
    disposition = gate.decide(ctx)
    assert disposition is ProposalDisposition.AWAIT_CONFIRMATION


def test_policy_escalates_for_low_confidence():
    gate = ProposalPolicyGate()
    prop = build_proposal(
        incident_id="INC-001",
        incident_type="NETWORK_ERROR",
        hypothesis="proxy drift",
        evidence_refs=["repair:probe:WININET-001"],
        candidate_action="reset_proxy_configuration",
        risk_class="low",
        rollback_strategy="restore_previous_proxy_config",
        verification_plan=["repair:targeted_check"],
        limitations=["single window"],
        confidence=0.30,
    )
    ctx = ProposalPolicyContext(proposal=prop, protected_operation=False)
    disposition = gate.decide(ctx)
    assert disposition is ProposalDisposition.ESCALATE


def test_policy_blocks_protected_operation():
    gate = ProposalPolicyGate()
    prop = build_proposal(
        incident_id="INC-001",
        incident_type="NETWORK_ERROR",
        hypothesis="proxy drift",
        evidence_refs=["repair:probe:WININET-001"],
        candidate_action="reset_proxy_configuration",
        risk_class="low",
        rollback_strategy="restore_previous_proxy_config",
        verification_plan=["repair:targeted_check"],
        limitations=["single window"],
    )
    ctx = ProposalPolicyContext(proposal=prop, protected_operation=True)
    disposition = gate.decide(ctx)
    assert disposition is ProposalDisposition.BLOCKED


# ---------------------------------------------------------------------------
# repair_plan_evaluator
# ---------------------------------------------------------------------------

def test_valid_proposal_passes_evaluator():
    evaluator = RepairPlanEvaluator()
    prop = build_proposal(
        incident_id="INC-001",
        incident_type="NETWORK_ERROR",
        hypothesis="proxy drift",
        evidence_refs=["repair:probe:WININET-001"],
        candidate_action="reset_proxy_configuration",
        risk_class="medium",
        rollback_strategy="restore_previous_proxy_config",
        verification_plan=["repair:targeted_check"],
        limitations=["single window"],
        confidence=0.82,
    )
    result = evaluator.evaluate(prop)
    assert result.proposal_valid is True
    assert result.policy_safe is True
    assert result.rollback_present is True
    assert result.verification_present is True
    assert result.forbidden_action_detected is False
    assert result.unsupported_action_detected is False
    assert result.evidence_refs_valid is True
    assert result.pass_ is True


def test_forbidden_action_detected_by_evaluator():
    """Defensive evaluator check for forbidden action that bypassed build_proposal."""
    evaluator = RepairPlanEvaluator()
    prop = RepairProposal(
        proposal_id="P-002",
        incident_id="INC-001",
        incident_type="NETWORK_ERROR",
        hypothesis="reset firewall",
        evidence_refs=["repair:probe:WININET-001"],
        candidate_action="reset_firewall",
        risk_class=RiskClass.HIGH,
        before_state_required=True,
        preview_required=True,
        confirmation_required=True,
        rollback_strategy="restore_firewall",
        verification_plan=["repair:targeted_check"],
        limitations=["single window"],
        confidence=0.82,
    )
    result = evaluator.evaluate(prop)
    assert result.forbidden_action_detected is True
    assert result.pass_ is False


def test_missing_rollback_detected_by_evaluator():
    """Defensive evaluator check for missing rollback that bypassed build_proposal."""
    evaluator = RepairPlanEvaluator()
    prop = RepairProposal(
        proposal_id="P-003",
        incident_id="INC-001",
        incident_type="NETWORK_ERROR",
        hypothesis="proxy drift",
        evidence_refs=["repair:probe:WININET-001"],
        candidate_action="targeted_repair",
        risk_class=RiskClass.LOW,
        before_state_required=False,
        preview_required=False,
        confirmation_required=False,
        rollback_strategy="",
        verification_plan=["repair:targeted_check"],
        limitations=["single window"],
        confidence=0.82,
    )
    result = evaluator.evaluate(prop)
    assert result.rollback_present is False
    assert result.pass_ is False


def test_missing_verification_detected_by_evaluator():
    """Defensive evaluator check for missing verification that bypassed build_proposal."""
    evaluator = RepairPlanEvaluator()
    prop = RepairProposal(
        proposal_id="P-004",
        incident_id="INC-001",
        incident_type="NETWORK_ERROR",
        hypothesis="proxy drift",
        evidence_refs=["repair:probe:WININET-001"],
        candidate_action="targeted_repair",
        risk_class=RiskClass.LOW,
        before_state_required=False,
        preview_required=False,
        confirmation_required=False,
        rollback_strategy="revert_patch",
        verification_plan=[],
        limitations=["single window"],
        confidence=0.82,
    )
    result = evaluator.evaluate(prop)
    assert result.verification_present is False
    assert result.pass_ is False


def test_none_proposal_evaluated_safely():
    evaluator = RepairPlanEvaluator()
    result = evaluator.evaluate(None)
    assert result.proposal_valid is False
    assert result.policy_safe is False
    assert result.unsupported_action_detected is True
    assert result.pass_ is False


# ---------------------------------------------------------------------------
# escalation
# ---------------------------------------------------------------------------

def test_escalation_is_explicit_not_generic_exception():
    esc = build_escalation(
        incident_id="INC-001",
        incident_type="NETWORK_ERROR",
        current_diagnosis="proxy drift",
        policy_reason="confirmation_required_by_policy",
        recommended_human_action="approve after reviewing preview",
        repair_proposal=build_proposal(
            incident_id="INC-001",
            incident_type="NETWORK_ERROR",
            hypothesis="proxy drift",
            evidence_refs=["repair:probe:WININET-001"],
            candidate_action="reset_proxy_configuration",
            risk_class="medium",
            rollback_strategy="restore_previous_proxy_config",
            verification_plan=["repair:targeted_check"],
            limitations=["single window"],
        ),
        attempt_history=["attempt=1:awaiting_confirmation"],
        risk_level="medium",
        human_review_required=True,
    )
    assert esc.incident_id == "INC-001"
    assert esc.human_review_required is True
    assert esc.repair_proposal is not None
    assert esc.attempt_history == ("attempt=1:awaiting_confirmation",)
    assert esc.to_dict()["repair_proposal"]["candidate_action"] == "reset_proxy_configuration"


# ---------------------------------------------------------------------------
# agent_harness demo flow
# ---------------------------------------------------------------------------

def test_harness_stops_before_live_mutation():
    model = HarnessFixtureClient(
        {
            "incident_type": "NETWORK_ERROR",
            "confidence": 0.82,
            "hypothesis": "proxy drift",
            "evidence_refs": ["repair:probe:WININET-001"],
            "limitations": ["single window"],
            "recommended_action": "targeted_repair",
        },
        model="structured-proposal-v1",
    )
    harness = BoundedRepairAgentHarness(model=model, max_attempts=3, evidence_namespace="repair")
    result = harness.run({
        "incident_id": "INC-WININET-001",
        "probe_id": "PROBE-WININET-001",
        "evidence_summary": "browser-only proxy drift",
        "failure_message": "browser connection failed; proxy inconsistent",
    })
    assert result.disposition in {"PREVIEW_READY", "ESCALATE"}
    assert result.attempt_count == 1
    assert result.retry_budget_remaining == 2
    assert result.proposal_id is not None
    assert result.verification_plan
    assert "repair:before_state_capture" in result.verification_plan


def test_harness_forbidden_action_escalates():
    """A model that recommends a forbidden action must fail at the diagnosis
    boundary, never reach the policy gate or sandbox."""
    model = HarnessFixtureClient(
        {
            "incident_type": "NETWORK_ERROR",
            "confidence": 0.82,
            "hypothesis": "reset firewall",
            "evidence_refs": ["repair:probe:WININET-001"],
            "limitations": ["single window"],
            "recommended_action": "reset_firewall",
        },
        model="structured-proposal-v1",
    )
    harness = BoundedRepairAgentHarness(model=model, max_attempts=3, evidence_namespace="repair")
    result = harness.run({
        "incident_id": "INC-FIREWALL-001",
        "probe_id": "PROBE-FIREWALL-001",
        "evidence_summary": "requested firewall reset",
        "failure_message": "requested firewall reset",
    })
    assert result.disposition == "ESCALATE"
    assert result.escalation is not None
    assert result.escalation.policy_reason == "llm_diagnosis_validation_failed"
    assert result.proposal is None


def test_harness_low_confidence_escalates():
    model = HarnessFixtureClient(
        {
            "incident_type": "NETWORK_ERROR",
            "confidence": 0.30,
            "hypothesis": "maybe proxy drift",
            "evidence_refs": ["repair:probe:WININET-001"],
            "limitations": [],
            "recommended_action": "targeted_repair",
        },
        model="structured-proposal-v1",
    )
    harness = BoundedRepairAgentHarness(model=model, max_attempts=3, evidence_namespace="repair")
    result = harness.run({
        "incident_id": "INC-LOWCONF-001",
        "probe_id": "PROBE-LOWCONF-001",
        "evidence_summary": "weak evidence",
        "failure_message": "weak evidence",
    })
    assert result.disposition == "ESCALATE"
    assert result.escalation is not None
    assert result.escalation.human_review_required is True

"""Tests for the portfolio upgrade correctness and reliability fixes.

Fix groups covered here:
  fix_1_production_proof_to_dict  - ProductionProofBundle.to_dict() now includes proof_hash
  fix_4_proposal_policy_risk_value- risk_class enum compared via .value (was str==enum)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ci_failure_orchestrator.models import Stage, Failure
from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.repair_proposal import (
    RepairProposal,
    RiskClass,
    build_proposal,
)
from ci_failure_orchestrator.production_proof import (
    ProductionProofBundle,
    ProductionPolicy,
    ProofArtifact,
    evaluate_production_gate,
    metrics_from_mapping,
    build_production_proof,
)
from ci_failure_orchestrator.patch_sandbox import WorktreePatchVerifier
from ci_failure_orchestrator.proposal_policy import (
    ProposalDisposition,
    ProposalPolicyContext,
    ProposalPolicyGate,
)


# ---------------------------------------------------------------- fix_1 ----
class TestProductionProofBundleToDict:
    """ProductionProofBundle.to_dict() must include the tamper-evident proof_hash."""

    def test_to_dict_includes_proof_hash(self) -> None:
        artifact = ProofArtifact(kind="audit", uri="audit.jsonl", digest="deadbeef")
        bundle = build_production_proof(
            repository="org/repo-a",
            run_id="123",
            commit_sha="abc123",
            gate_decision="PASS",
            evaluator_score=0.98,
            regression_free=True,
            canary_decision="promote",
            slo_met=True,
            artifacts=[artifact],
        )
        payload = bundle.to_dict()
        assert payload["proof_hash"] == bundle.proof_hash
        assert len(payload["proof_hash"]) == 64

    def test_to_dict_field_set_exact(self) -> None:
        bundle = build_production_proof(
            repository="r", run_id="1", commit_sha="c", gate_decision="PASS",
            evaluator_score=0.9, regression_free=False, canary_decision="hold",
            slo_met=False,
        )
        expected = {
            "repository", "run_id", "commit_sha", "gate_decision", "evaluator_score",
            "regression_free", "canary_decision", "slo_met", "artifacts",
            "created_at", "proof_hash",
        }
        assert set(bundle.to_dict().keys()) == expected

    def test_build_production_proof_hash_is_stable_for_same_input(self) -> None:
        created = "2026-01-01T00:00:00+00:00"
        a = build_production_proof(
            repository="r", run_id="1", commit_sha="c", gate_decision="PASS",
            evaluator_score=0.9, regression_free=True, canary_decision="promote",
            slo_met=True, created_at=created,
        )
        b = build_production_proof(
            repository="r", run_id="1", commit_sha="c", gate_decision="PASS",
            evaluator_score=0.9, regression_free=True, canary_decision="promote",
            slo_met=True, created_at=created,
        )
        assert a.proof_hash == b.proof_hash

    def test_evaluate_production_gate_cacheable_policy(self) -> None:
        policy = ProductionPolicy(min_repair_success_rate=0.90)
        metrics = metrics_from_mapping({
            "repair_success_rate": 0.92,
            "regression_rate": 0.01,
            "p95_latency_seconds": 20.0,
            "cost_per_success_usd": 0.10,
            "critical_security_findings": 0,
        })
        result = evaluate_production_gate(metrics, policy)
        assert result.passed is True
        assert result.checks["repair_success_rate"] is True


# ---------------------------------------------------------------- fix_4 ----
class TestProposalPolicyRiskValue:
    """ProposalPolicyGate compares risk_class via .value (enum == str was always False)."""

    def _gate(self):
        return ProposalPolicyGate()

    def _ctx(self, *, risk_value: str) -> ProposalDisposition:
        proposal = build_proposal(
            incident_id="INC-1",
            incident_type="TYPE_ERROR",
            hypothesis="test",
            evidence_refs=[],
            candidate_action="targeted_repair",
            risk_class=risk_value,
            rollback_strategy="revert_patch",
            verification_plan=["targeted_check"],
            limitations=[],
            confidence=0.9,
            model="fixture",
        )
        return self._gate().decide(
            ProposalPolicyContext(
                proposal=proposal,
                evidence_level=2,
                human_review_required=False,
                protected_operation=False,
            )
        )

    def test_high_risk_returns_await_confirmation(self) -> None:
        assert self._ctx(risk_value="high") == ProposalDisposition.AWAIT_CONFIRMATION

    def test_critical_risk_returns_await_confirmation(self) -> None:
        assert self._ctx(risk_value="critical") == ProposalDisposition.AWAIT_CONFIRMATION

    def test_low_risk_returns_preview_ready(self) -> None:
        assert self._ctx(risk_value="low") == ProposalDisposition.PREVIEW_READY

    def test_medium_risk_returns_preview_ready(self) -> None:
        assert self._ctx(risk_value="medium") == ProposalDisposition.PREVIEW_READY


# ---------------------------------------------------------------- fixtures ----
@pytest.fixture
def proposal_high() -> RepairProposal:
    return build_proposal(
        incident_id="INC-1",
        incident_type="TYPE_ERROR",
        hypothesis="high risk hypothesis",
        evidence_refs=[],
        candidate_action="targeted_repair",
        risk_class="high",
        rollback_strategy="revert_patch",
        verification_plan=["targeted_check"],
        limitations=[],
        confidence=0.9,
        model="fixture",
    )


@pytest.fixture
def proposal_low() -> RepairProposal:
    return build_proposal(
        incident_id="INC-2",
        incident_type="LINT_ERROR",
        hypothesis="low risk hypothesis",
        evidence_refs=[],
        candidate_action="build_config_fix",
        risk_class="low",
        rollback_strategy="revert_patch",
        verification_plan=["targeted_check"],
        limitations=[],
        confidence=0.9,
        model="fixture",
    )

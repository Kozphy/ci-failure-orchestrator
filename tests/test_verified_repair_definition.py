from dataclasses import replace

import pytest
from _research_factories import facts

from ci_failure_orchestrator.foundation.remediation import (
    LOW,
    GateStatus,
    RemediationState,
    VerificationResult,
    decide_remediation,
    is_verified_fix,
)
from research.repair import ACCEPTED, ESCALATED, REJECTED, locally_verified, p_composed, verified_without_policy

PASS = GateStatus.PASSED

FULL = VerificationResult(
    repair_proposed=True, patch_applied=True, original_failure_reproduced=True, original_failure_resolved=True,
    targeted_test_passed=True, affected_tests=PASS, regression_suite=PASS, test_count_decreased=False,
    skipped_tests_increased=False, coverage=PASS, lint=PASS, typecheck=PASS, security=PASS, build=PASS,
    behavioral_invariants=PASS, policy_outcome="APPROVE", risk_level=LOW, real_ci_passed=True,
)


def test_all_eight_requirements_met_is_verified_fixed():
    assert is_verified_fix(FULL)
    assert decide_remediation(FULL).state is RemediationState.VERIFIED_FIXED


def test_local_evidence_without_real_ci_is_not_verified_fixed():
    local = replace(FULL, real_ci_passed=None)
    assert not is_verified_fix(local)
    assert decide_remediation(local).state is not RemediationState.VERIFIED_FIXED
    assert locally_verified(local)


@pytest.mark.parametrize(
    "change",
    [
        {"original_failure_reproduced": None},
        {"patch_applied": False},
        {"targeted_test_passed": None},
        {"regression_suite": GateStatus.NOT_RUN},
        {"regression_suite": GateStatus.FAILED},
        {"skipped_tests_increased": True},
        {"test_count_decreased": None},
        {"target_test_missing": True},
        {"forbidden_diff_detected": True},
        {"security": GateStatus.NOT_RUN},
        {"policy_outcome": "REJECT"},
        {"policy_outcome": None},
        {"new_test_failures": ("tests/test_other.py::test_x",)},
    ],
)
def test_any_missing_or_failing_requirement_blocks_verification(change):
    v = replace(FULL, **change)
    assert not is_verified_fix(v)
    assert not locally_verified(v)


def test_removing_the_policy_gate_does_not_remove_the_other_requirements():
    assert verified_without_policy(replace(FULL, policy_outcome="REJECT"))
    assert not verified_without_policy(replace(FULL, policy_outcome="REJECT", forbidden_diff_detected=True))
    assert not verified_without_policy(None)


def test_what_if_verification_never_counts_as_locally_verified():
    fact = facts("skip", "fake_fix", policy="REJECT", whatif=True)
    assert fact.locally_verified is False


def test_p_accepts_only_policy_approved_and_locally_verified_candidates():
    accepted = p_composed("P", "c", [facts("good", "correct")], 3)
    assert accepted.decision == ACCEPTED and accepted.reason == "locally_verified"
    escalated = p_composed("P", "c", [facts("x", "fake_fix", policy="ESCALATE", verified=False)], 3)
    assert escalated.decision == ESCALATED
    unverified = p_composed("P", "c", [facts("y", "semantically_wrong", verified=False, oracle=False)], 3)
    assert unverified.decision == REJECTED and unverified.reason.startswith("verification_")

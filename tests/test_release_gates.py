from dataclasses import replace

from ci_failure_orchestrator.release_gates import (
    ProductionSuccessResult,
    ReleaseReadinessResult,
    production_success,
    release_ready,
    repair_success,
)
from ci_failure_orchestrator.repair_state_machine import VerificationResult


def _repair() -> VerificationResult:
    return VerificationResult(
        targeted_tests_passed=True,
        full_regression_passed=True,
        policy_gate_passed=True,
        ci_green=True,
        security_gate_passed=True,
        test_weakening_detected=False,
        regression_detected=False,
    )


def _release() -> ReleaseReadinessResult:
    return ReleaseReadinessResult(
        repair=_repair(),
        artifact_integrity_passed=True,
        dependency_gate_passed=True,
        deployment_validation_passed=True,
        required_approvals_passed=True,
        rollback_ready=True,
    )


def _production() -> ProductionSuccessResult:
    return ProductionSuccessResult(
        release=_release(),
        canary_healthy=True,
        slo_passed=True,
        error_budget_ok=True,
        observability_healthy=True,
        production_regression_detected=False,
    )


def test_all_three_canonical_gates_pass_on_complete_evidence() -> None:
    repair = _repair()
    release = _release()
    production = _production()
    assert repair_success(repair)
    assert release_ready(release)
    assert production_success(production)


def test_release_can_never_mask_failed_repair() -> None:
    failed_repair = replace(_repair(), ci_green=False)
    release = replace(_release(), repair=failed_repair)
    assert not release_ready(release)


def test_each_release_requirement_is_mandatory() -> None:
    release = _release()
    for field in (
        "artifact_integrity_passed",
        "dependency_gate_passed",
        "deployment_validation_passed",
        "required_approvals_passed",
        "rollback_ready",
    ):
        assert not release_ready(replace(release, **{field: False}))


def test_production_can_never_mask_failed_release() -> None:
    failed_release = replace(_release(), rollback_ready=False)
    production = replace(_production(), release=failed_release)
    assert not production_success(production)


def test_each_production_requirement_is_mandatory() -> None:
    production = _production()
    for field in (
        "canary_healthy",
        "slo_passed",
        "error_budget_ok",
        "observability_healthy",
    ):
        assert not production_success(replace(production, **{field: False}))
    assert not production_success(
        replace(production, production_regression_detected=True)
    )

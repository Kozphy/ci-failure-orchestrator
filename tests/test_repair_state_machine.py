from ci_failure_orchestrator.github_repair_adapter import FailedCheck
from ci_failure_orchestrator.repair_state_machine import (
    RepairCoordinator,
    RepairIncident,
    RepairState,
    VerificationResult,
    WorkerResult,
    verify_transition_chain,
)


def _incident() -> RepairIncident:
    return RepairIncident(
        incident_id="incident-1",
        check=FailedCheck(
            workflow="ci",
            job="test",
            failed_step="pytest",
            log_excerpt="AssertionError in unit test",
            changed_paths=("ci_failure_orchestrator/platform.py",),
        ),
    )


def test_medium_risk_path_requires_review_authority() -> None:
    incident = _incident()
    coordinator = RepairCoordinator()
    plan = coordinator.plan(incident)
    assert incident.state is RepairState.PLANNED
    assert plan.task is not None
    assert plan.task.authority.value == "patch_requires_review"


def test_successful_repair_reaches_green() -> None:
    incident = _incident()
    coordinator = RepairCoordinator()
    plan = coordinator.plan(incident)
    assert plan.task is not None
    coordinator.dispatch(incident, plan.task)
    coordinator.accept_worker_result(
        incident,
        WorkerResult(
            patch_proposed=True,
            changed_paths=("ci_failure_orchestrator/platform.py",),
            changed_lines=8,
            cost_usd=0.12,
        ),
    )
    coordinator.verify(
        incident,
        VerificationResult(
            targeted_tests_passed=True,
            full_regression_passed=True,
            policy_gate_passed=True,
            ci_green=True,
        ),
    )
    assert incident.state is RepairState.GREEN
    assert verify_transition_chain(incident.transitions)


def test_safety_failure_denies_candidate() -> None:
    incident = _incident()
    coordinator = RepairCoordinator()
    plan = coordinator.plan(incident)
    assert plan.task is not None
    coordinator.dispatch(incident, plan.task)
    coordinator.accept_worker_result(
        incident,
        WorkerResult(patch_proposed=True, test_weakening_detected=True),
    )
    assert incident.state is RepairState.DENIED


def test_failed_verification_can_retry() -> None:
    incident = _incident()
    coordinator = RepairCoordinator()
    plan = coordinator.plan(incident)
    assert plan.task is not None
    coordinator.dispatch(incident, plan.task)
    coordinator.accept_worker_result(incident, WorkerResult(patch_proposed=True))
    coordinator.verify(
        incident,
        VerificationResult(
            targeted_tests_passed=False,
            full_regression_passed=False,
            policy_gate_passed=True,
            ci_green=False,
        ),
    )
    assert incident.state is RepairState.RERUNNING
    coordinator.prepare_retry(incident)
    assert incident.state is RepairState.DETECTED


def test_retry_budget_eventually_denies() -> None:
    incident = _incident()
    coordinator = RepairCoordinator()
    for _ in range(3):
        plan = coordinator.plan(incident)
        assert plan.task is not None
        coordinator.dispatch(incident, plan.task)
        coordinator.accept_worker_result(incident, WorkerResult(patch_proposed=True))
        coordinator.verify(
            incident,
            VerificationResult(False, False, True, False),
        )
        coordinator.prepare_retry(incident)
    plan = coordinator.plan(incident)
    assert plan.task is None
    assert incident.state is RepairState.DENIED


def test_policy_gate_can_require_review() -> None:
    incident = _incident()
    coordinator = RepairCoordinator()
    plan = coordinator.plan(incident)
    assert plan.task is not None
    coordinator.dispatch(incident, plan.task)
    coordinator.accept_worker_result(incident, WorkerResult(patch_proposed=True))
    coordinator.verify(
        incident,
        VerificationResult(True, True, False, False),
    )
    assert incident.state is RepairState.REVIEW_REQUIRED

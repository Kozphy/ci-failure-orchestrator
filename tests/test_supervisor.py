from ci_failure_orchestrator.supervisor import (
    RepairAuthority,
    RepairRequest,
    RetryBudget,
    RiskLevel,
    SupervisorPolicy,
    evaluate_repair,
)


def test_low_risk_lint_can_auto_patch() -> None:
    decision = evaluate_repair(
        RepairRequest(
            failure_class="lint",
            changed_paths=("src/example.py",),
            predicted_changed_lines=12,
        )
    )
    assert decision.risk is RiskLevel.LOW
    assert decision.authority is RepairAuthority.AUTONOMOUS_PATCH
    assert decision.allowed is True
    assert "full_regression" in decision.required_gates


def test_application_logic_requires_review() -> None:
    decision = evaluate_repair(
        RepairRequest(
            failure_class="unit_test_failure",
            changed_paths=("ci_failure_orchestrator/platform.py",),
            predicted_changed_lines=40,
        )
    )
    assert decision.risk is RiskLevel.MEDIUM
    assert decision.authority is RepairAuthority.PATCH_REQUIRES_REVIEW
    assert "human_review" in decision.required_gates


def test_workflow_change_is_rca_only() -> None:
    decision = evaluate_repair(
        RepairRequest(
            failure_class="workflow_syntax",
            changed_paths=(".github/workflows/ci.yml",),
        )
    )
    assert decision.risk is RiskLevel.HIGH
    assert decision.authority is RepairAuthority.RCA_ONLY
    assert "human_approval" in decision.required_gates


def test_secret_surface_is_denied() -> None:
    decision = evaluate_repair(
        RepairRequest(
            failure_class="typing",
            changed_paths=("config/production-secrets.yaml",),
        )
    )
    assert decision.risk is RiskLevel.CRITICAL
    assert decision.authority is RepairAuthority.DENY
    assert decision.allowed is False


def test_regression_always_fails_closed() -> None:
    decision = evaluate_repair(
        RepairRequest(
            failure_class="lint",
            changed_paths=("src/example.py",),
            regression_detected=True,
        )
    )
    assert decision.authority is RepairAuthority.DENY
    assert "regression_detected" in decision.reasons


def test_test_weakening_is_denied() -> None:
    decision = evaluate_repair(
        RepairRequest(
            failure_class="deterministic_test_fixture",
            changed_paths=("tests/test_example.py",),
            test_weakening_detected=True,
        )
    )
    assert decision.authority is RepairAuthority.DENY
    assert "test_weakening_detected" in decision.reasons


def test_retry_budget_stops_agent_loop() -> None:
    policy = SupervisorPolicy(budget=RetryBudget(max_attempts=2))
    decision = evaluate_repair(
        RepairRequest(
            failure_class="lint",
            changed_paths=("src/example.py",),
            attempt=3,
        ),
        policy,
    )
    assert decision.authority is RepairAuthority.DENY
    assert "retry_budget_exhausted" in decision.reasons


def test_change_budget_stops_large_patch() -> None:
    policy = SupervisorPolicy(
        budget=RetryBudget(max_changed_files=2, max_changed_lines=20)
    )
    decision = evaluate_repair(
        RepairRequest(
            failure_class="lint",
            changed_paths=("a.py", "b.py", "c.py"),
            predicted_changed_lines=50,
        ),
        policy,
    )
    assert decision.authority is RepairAuthority.DENY
    assert "changed_file_budget_exhausted" in decision.reasons
    assert "changed_line_budget_exhausted" in decision.reasons


def test_security_finding_is_critical_even_on_low_risk_failure() -> None:
    decision = evaluate_repair(
        RepairRequest(
            failure_class="formatting",
            changed_paths=("src/example.py",),
            security_finding=True,
        )
    )
    assert decision.risk is RiskLevel.CRITICAL
    assert decision.authority is RepairAuthority.DENY


def test_forbidden_actions_are_propagated_to_worker_contract() -> None:
    decision = evaluate_repair(
        RepairRequest(failure_class="lint", changed_paths=("src/example.py",))
    )
    assert "delete_failing_tests" in decision.forbidden_actions
    assert "disable_required_checks" in decision.forbidden_actions

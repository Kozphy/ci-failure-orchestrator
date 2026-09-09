from ci_failure_orchestrator.github_repair_adapter import (
    FailedCheck,
    build_repair_plan,
    classify_failed_check,
    summarize_failed_jobs,
)
from ci_failure_orchestrator.supervisor import RepairAuthority, RiskLevel


def test_classifies_pytest_failure_as_application_failure() -> None:
    check = FailedCheck("ci", "test", "Tests with coverage", "pytest: 1 failed")
    assert classify_failed_check(check) == "unit_test_failure"


def test_low_risk_lint_builds_autonomous_task() -> None:
    plan = build_repair_plan(
        FailedCheck(
            "ci",
            "lint",
            "Run ruff",
            "ruff check failed",
            changed_paths=("src/app.py",),
        )
    )
    assert plan.decision.risk is RiskLevel.LOW
    assert plan.decision.authority is RepairAuthority.AUTONOMOUS_PATCH
    assert plan.task is not None
    assert plan.should_rerun_after_patch is True
    assert "delete_failing_tests" in plan.task.forbidden_actions


def test_workflow_surface_stays_rca_only() -> None:
    plan = build_repair_plan(
        FailedCheck(
            "ci",
            "workflow-validation",
            "workflow yaml syntax",
            "invalid workflow syntax",
            changed_paths=(".github/workflows/ci.yml",),
        )
    )
    assert plan.decision.risk is RiskLevel.HIGH
    assert plan.decision.authority is RepairAuthority.RCA_ONLY
    assert plan.should_rerun_after_patch is False


def test_unknown_failure_requires_review_not_autonomous_patch() -> None:
    plan = build_repair_plan(
        FailedCheck("ci", "mystery", "unknown", "unexpected infrastructure event")
    )
    assert plan.decision.risk is RiskLevel.MEDIUM
    assert plan.decision.authority is RepairAuthority.PATCH_REQUIRES_REVIEW


def test_retry_budget_stops_repair_loop() -> None:
    plan = build_repair_plan(
        FailedCheck("ci", "lint", "Run lint", "lint failed", ("src/app.py",)),
        attempt=4,
    )
    assert plan.decision.authority is RepairAuthority.DENY
    assert plan.task is None
    assert plan.should_rerun_after_patch is False


def test_summarize_failed_jobs_extracts_first_failed_step() -> None:
    checks = summarize_failed_jobs(
        [
            {
                "workflow": "ci",
                "name": "test",
                "conclusion": "failure",
                "steps": [
                    {"name": "Install", "conclusion": "success"},
                    {"name": "pytest", "conclusion": "failure"},
                ],
            },
            {"workflow": "security", "name": "scan", "conclusion": "success"},
        ]
    )
    assert len(checks) == 1
    assert checks[0].failed_step == "pytest"

from ci_failure_orchestrator.control_plane import ControlPlaneRun, EvaluationResult, RepairPlan, RunStatus
from ci_failure_orchestrator.models import Failure
from ci_failure_orchestrator.repair_benchmark import RepairBenchmarkCase, evaluate_repairs


def run_factory(failure: Failure) -> ControlPlaneRun:
    if failure.error_type == "UNKNOWN":
        run = ControlPlaneRun(
            incident_id=f"CI-{failure.stage}",
            root_cause=failure.message,
            plan=RepairPlan(
                hypothesis=failure.message,
                evidence=[failure.error_type],
                steps=["reproduce", "repair", "test"],
                risk_score=0.9,
                confidence=0.5,
                estimated_cost_usd=0.5,
            ),
        )
        run.evaluation = EvaluationResult(False, 0.2, {"tests": False, "security": False})
    else:
        run = ControlPlaneRun(
            incident_id=f"CI-{failure.stage}",
            root_cause=failure.message,
            plan=RepairPlan(
                hypothesis=failure.message,
                evidence=[failure.error_type],
                steps=["reproduce", "repair", "test"],
                risk_score=0.3,
                confidence=0.9,
                estimated_cost_usd=0.1,
            ),
        )
        run.evaluation = EvaluationResult(True, 0.95, {"tests": True, "security": True})
    run.policy_gate()
    return run


def test_repair_benchmark_reports_success_cost_latency() -> None:
    cases = [
        RepairBenchmarkCase(
            "type-error",
            Failure("typecheck", "TYPE_ERROR", "mypy incompatible type in assignment"),
            RunStatus.DEPLOYING,
        ),
        RepairBenchmarkCase(
            "unknown",
            Failure("build", "UNKNOWN", "something unprecedented happened"),
            RunStatus.ESCALATED,
        ),
    ]
    results, summary = evaluate_repairs(cases, run_factory)
    assert summary.cases == 2
    assert summary.passed == 2
    assert summary.success_rate == 1.0
    assert summary.mean_cost >= 0.0
    assert summary.median_latency_ms >= 0.0
    assert results[0].status == "deploying"
    assert results[1].status == "escalated"

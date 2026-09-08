from ci_failure_orchestrator.control_plane import Decision, RepairControlPlane
from ci_failure_orchestrator.control_plane_run import (
    AgentRun,
    ControlPlaneRun,
    EvaluationResult,
    RepairPlan,
    RunStatus,
)
from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.models import Failure, Stage
from ci_failure_orchestrator.policy import DefaultRepairPolicy
from ci_failure_orchestrator.production import InMemoryEvidenceSink, RegressionAwareEvaluator
from ci_failure_orchestrator.repair_agents import DeterministicRepairAgent, GeneralCodingAgent


def graph() -> PipelineGraph:
    return PipelineGraph([
        Stage("lint"),
        Stage("typecheck", depends_on=("lint",)),
        Stage("unit", depends_on=("typecheck",)),
        Stage("integration", depends_on=("unit",)),
        Stage("build", depends_on=("integration",)),
    ])


def test_release_after_verified_repair() -> None:
    evidence = InMemoryEvidenceSink()
    control = RepairControlPlane(
        graph(),
        [DeterministicRepairAgent(), GeneralCodingAgent()],
        RegressionAwareEvaluator(tests_passed=True, regression_free=True, score=0.97),
        DefaultRepairPolicy(),
        evidence,
    )
    failure = Failure("typecheck", "", "mypy incompatible type in assignment")
    assert control.run(failure) is Decision.RELEASE
    assert failure.error_type == "TYPE_ERROR"
    assert [e["event"] for e in evidence.events] == ["classified", "evaluated", "policy_decision"]


def test_regression_blocks_release() -> None:
    evidence = InMemoryEvidenceSink()
    control = RepairControlPlane(
        graph(),
        [DeterministicRepairAgent(), GeneralCodingAgent()],
        RegressionAwareEvaluator(tests_passed=True, regression_free=False, score=0.99),
        DefaultRepairPolicy(),
        evidence,
    )
    failure = Failure("unit", "", "AssertionError expected 2 got 3")
    assert control.run(failure) is Decision.BLOCK


def test_unknown_failure_escalates() -> None:
    evidence = InMemoryEvidenceSink()
    control = RepairControlPlane(
        graph(),
        [DeterministicRepairAgent(), GeneralCodingAgent()],
        RegressionAwareEvaluator(),
        DefaultRepairPolicy(),
        evidence,
    )
    failure = Failure("build", "", "something unprecedented happened")
    assert control.run(failure) is Decision.ESCALATE
    assert evidence.events[-1]["payload"]["reason"] == "no_repair_plan"


def test_cost_budget_stops_autonomy() -> None:
    evidence = InMemoryEvidenceSink()
    control = RepairControlPlane(
        graph(),
        [DeterministicRepairAgent()],
        RegressionAwareEvaluator(),
        DefaultRepairPolicy(),
        evidence,
        max_cost=0.001,
    )
    failure = Failure("typecheck", "", "mypy incompatible type")
    assert control.run(failure) is Decision.ESCALATE
    assert evidence.events[-1]["payload"]["reason"] == "budget_or_stopping_condition"


def _plan(risk: float) -> RepairPlan:
    return RepairPlan(
        hypothesis="schema mismatch",
        evidence=["integration failure"],
        steps=["reproduce", "repair", "regression test"],
        risk_score=risk,
        confidence=0.9,
        estimated_cost_usd=0.2,
    )


def test_low_risk_pass_moves_to_deploy() -> None:
    run = ControlPlaneRun("CI-1", plan=_plan(0.2))
    run.evaluation = EvaluationResult(True, 0.95, {"tests": True})
    assert run.policy_gate() == "RUN_FULL_PIPELINE"
    assert run.status is RunStatus.DEPLOYING
    assert run.approval and not run.approval.required


def test_medium_risk_pass_requires_human_approval() -> None:
    run = ControlPlaneRun("CI-2", plan=_plan(0.7))
    run.evaluation = EvaluationResult(True, 0.95, {"tests": True})
    run.policy_gate()
    assert run.status is RunStatus.AWAITING_APPROVAL
    assert run.approval and run.approval.required


def test_high_risk_failure_escalates() -> None:
    run = ControlPlaneRun("CI-3", plan=_plan(0.9))
    run.evaluation = EvaluationResult(False, 0.2, {"tests": False})
    assert run.policy_gate() == "ESCALATE_HUMAN"
    assert run.status is RunStatus.ESCALATED


def test_telemetry_aggregates_agent_usage() -> None:
    run = ControlPlaneRun("CI-4")
    run.agents = [
        AgentRun("a", "repair", tokens=100, cost_usd=0.1, latency_ms=20),
        AgentRun("b", "evaluate", tokens=200, cost_usd=0.2, latency_ms=30),
    ]
    assert run.telemetry()["llm_tokens"] == 300
    assert run.telemetry()["cost_usd"] == 0.3
    assert run.telemetry()["latency_ms"] == 50

from ci_failure_orchestrator.control_plane import (
    AgentRun,
    ControlPlaneRun,
    EvaluationResult,
    RepairPlan,
    RunStatus,
)


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

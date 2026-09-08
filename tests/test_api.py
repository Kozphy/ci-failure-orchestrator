from ci_failure_orchestrator.api import ControlPlaneAPI
from ci_failure_orchestrator.control_plane_run import (
    ControlPlaneRun,
    EvaluationResult,
    ProductionEvidence,
    RepairPlan,
    RunStatus,
)


def _run(risk: float = 0.7) -> ControlPlaneRun:
    run = ControlPlaneRun(
        incident_id="CI-42",
        root_cause="schema mismatch",
        plan=RepairPlan(
            hypothesis="schema mismatch",
            evidence=["integration failure"],
            steps=["reproduce", "repair", "regression test"],
            risk_score=risk,
            confidence=0.91,
            estimated_cost_usd=0.25,
        ),
    )
    run.evaluation = EvaluationResult(True, 0.96, {"tests": True, "security": True})
    run.policy_gate()
    return run


def test_graph_contract_exposes_root_cause_and_steps() -> None:
    api = ControlPlaneAPI({"run-1": _run()})
    graph = api.get_failure_graph("run-1")
    assert graph["nodes"][0]["kind"] == "root_cause"
    assert graph["edges"][0] == {"source": "root-cause", "target": "step-1"}


def test_approval_queue_and_decision() -> None:
    api = ControlPlaneAPI({"run-1": _run()})
    assert len(api.get_approval_queue()) == 1
    payload = api.decide_approval("run-1", approved=True, reviewer="operator@example.com")
    assert payload["status"] == RunStatus.DEPLOYING.value
    assert payload["approval"]["approved"] is True


def test_production_evidence_contract() -> None:
    run = _run(risk=0.2)
    run.evidence = ProductionEvidence(
        incident_id=run.incident_id,
        repair_commit="abc123",
        tests_passed=481,
        regressions=0,
        deployment_strategy="canary",
        rollback_ready=True,
        production_verified=True,
    )
    api = ControlPlaneAPI({"run-1": run})
    evidence = api.get_production_evidence("run-1")
    assert evidence is not None
    assert evidence["production_verified"] is True


def test_unknown_run_is_explicit() -> None:
    api = ControlPlaneAPI()
    try:
        api.get_run("missing")
    except KeyError as exc:
        assert "unknown run_id" in str(exc)
    else:
        raise AssertionError("expected KeyError")

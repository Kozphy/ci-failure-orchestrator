from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.models import Failure, RankedFailure, Stage
from ci_failure_orchestrator.repair_planner import DeterministicRepairPlanner


def _ranked(error_type: str, *, metadata=None, confidence=0.9):
    return RankedFailure(
        failure=Failure(
            "typecheck",
            error_type,
            confidence=confidence,
            metadata=metadata or {},
        ),
        score=0.91,
        downstream_count=2,
        depth=0,
        causal_matches=2,
        reasons=["upstream impact"],
    )


def test_planner_builds_bounded_repair_plan():
    graph = PipelineGraph(
        [
            Stage("typecheck"),
            Stage("unit", ("typecheck",)),
            Stage("deploy", ("unit",)),
        ]
    )
    planner = DeterministicRepairPlanner()

    plan = planner.plan(
        graph,
        _ranked("TYPE_ERROR", metadata={"files": ["src/service.py"]}),
        {"typecheck", "unit", "deploy"},
    )

    assert plan.root_stage == "typecheck"
    assert plan.target_files == ("src/service.py",)
    assert plan.risk == "low"
    assert plan.requires_human_approval is False
    assert [step.stage for step in plan.verification] == [
        "typecheck",
        "unit",
        "deploy",
        "*",
    ]


def test_high_risk_failure_requires_human_approval():
    graph = PipelineGraph([Stage("typecheck")])
    planner = DeterministicRepairPlanner()

    plan = planner.plan(
        graph,
        _ranked("SECURITY_ERROR"),
        {"typecheck"},
    )

    assert plan.risk == "high"
    assert plan.requires_human_approval is True


def test_unknown_failure_fails_safe():
    graph = PipelineGraph([Stage("typecheck")])
    planner = DeterministicRepairPlanner()

    plan = planner.plan(
        graph,
        _ranked("UNKNOWN_FAILURE"),
        {"typecheck"},
    )

    assert plan.risk == "high"
    assert plan.requires_human_approval is True
    assert plan.rollback == "revert_patch"

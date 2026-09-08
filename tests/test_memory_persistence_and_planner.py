from pathlib import Path

from ci_failure_orchestrator.failure_memory import FailureMemoryAgent, IncidentMemory
from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.memory_aware_planner import MemoryAwareRepairPlanner
from ci_failure_orchestrator.models import Failure, RankedFailure, Stage
from ci_failure_orchestrator.sqlite_memory import SQLiteIncidentStore


def _ranked_failure():
    failure = Failure(
        "typecheck",
        "TYPE_ERROR",
        message="mypy Optional str incompatible assignment",
        confidence=0.95,
        metadata={"files": ["src/foo.py"]},
    )
    return RankedFailure(failure, 0.95, 0, 0, 1, ["upstream"])


def test_sqlite_store_persists_incidents(tmp_path: Path):
    db = tmp_path / "incidents.db"
    store = SQLiteIncidentStore(db)
    store.add(IncidentMemory(
        incident_id="i-1",
        error_signature="mypy Optional str incompatible assignment",
        failure_class="TYPE_ERROR",
        root_stage="typecheck",
        changed_files=("src/foo.py",),
        successful_patch_summary="guard Optional before assignment",
        affected_tests=("tests/test_foo.py",),
        retries=1,
        cost_usd=0.02,
        latency_ms=800,
    ))

    reopened = SQLiteIncidentStore(db)
    incidents = tuple(reopened.all())
    assert len(incidents) == 1
    assert incidents[0].successful_patch_summary == "guard Optional before assignment"
    assert incidents[0].affected_tests == ("tests/test_foo.py",)


def test_memory_aware_planner_adds_successful_history(tmp_path: Path):
    store = SQLiteIncidentStore(tmp_path / "memory.db")
    memory = FailureMemoryAgent(store)
    memory.remember(IncidentMemory(
        incident_id="i-2",
        error_signature="mypy Optional str incompatible assignment",
        failure_class="TYPE_ERROR",
        root_stage="typecheck",
        changed_files=("src/foo.py",),
        successful_patch_summary="guard Optional before assignment",
    ))
    planner = MemoryAwareRepairPlanner(memory)
    graph = PipelineGraph([Stage("typecheck")])
    plan = planner.plan(graph, _ranked_failure(), {"typecheck"})

    assert "Historical successful repair evidence" in plan.proposed_change
    assert plan.metadata["memory_matches"] == "1"
    assert plan.metadata["memory_successful_matches"] == "1"


def test_regression_history_is_recorded_but_not_promoted(tmp_path: Path):
    store = SQLiteIncidentStore(tmp_path / "memory.db")
    memory = FailureMemoryAgent(store)
    memory.remember(IncidentMemory(
        incident_id="i-3",
        error_signature="mypy Optional str incompatible assignment",
        failure_class="TYPE_ERROR",
        root_stage="typecheck",
        changed_files=("src/foo.py",),
        successful_patch_summary="unsafe cast",
        regression_detected=True,
    ))
    planner = MemoryAwareRepairPlanner(memory)
    graph = PipelineGraph([Stage("typecheck")])
    plan = planner.plan(graph, _ranked_failure(), {"typecheck"})

    assert "unsafe cast" not in plan.proposed_change
    assert plan.metadata["memory_regression_matches"] == "1"
    assert plan.metadata["memory_successful_matches"] == "0"

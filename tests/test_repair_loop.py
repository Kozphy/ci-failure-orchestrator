from pathlib import Path

from ci_failure_orchestrator.repair import RepairPlanner, SandboxRepairExecutor
from ci_failure_orchestrator.repair_loop import run_repair_case, summarize_repair_runs


def test_repair_loop_stops_after_success(tmp_path: Path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "value.txt").write_text("BROKEN\n", encoding="utf-8")

    case = {
        "id": "replace-broken-token",
        "repair_candidates": [
            {"strategy": "replace_text", "target_path": "value.txt", "old": "BROKEN", "new": "FIXED"},
            {"strategy": "append_line", "target_path": "value.txt", "line": "unused"},
        ],
    }

    def verify(repo: Path):
        ok = (repo / "value.txt").read_text(encoding="utf-8").strip() == "FIXED"
        return ok, not ok, "", ""

    run = run_repair_case(fixture, case, RepairPlanner(), SandboxRepairExecutor(verify), retry_budget=2)
    assert run.resolved is True
    assert run.escalated is False
    assert len(run.attempts) == 1


def test_repair_loop_retries_then_escalates(tmp_path: Path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "value.txt").write_text("BROKEN\n", encoding="utf-8")

    case = {
        "id": "unresolved",
        "repair_candidates": [
            {"strategy": "append_line", "target_path": "value.txt", "line": "still-broken"},
            {"strategy": "replace_text", "target_path": "value.txt", "old": "BROKEN", "new": "ALSO_BROKEN"},
        ],
    }

    def verify(repo: Path):
        return False, True, "", "verification failed"

    run = run_repair_case(fixture, case, RepairPlanner(), SandboxRepairExecutor(verify), retry_budget=2)
    assert run.resolved is False
    assert run.escalated is True
    assert len(run.attempts) == 2


def test_metrics_are_measured_from_runs(tmp_path: Path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "value.txt").write_text("BROKEN\n", encoding="utf-8")

    success_case = {
        "id": "success",
        "repair_candidates": [
            {"strategy": "replace_text", "target_path": "value.txt", "old": "BROKEN", "new": "FIXED"},
        ],
    }
    failure_case = {
        "id": "failure",
        "repair_candidates": [
            {"strategy": "append_line", "target_path": "value.txt", "line": "NOPE"},
        ],
    }

    def verify(repo: Path):
        ok = "FIXED" in (repo / "value.txt").read_text(encoding="utf-8")
        return ok, not ok, "", ""

    planner = RepairPlanner()
    executor = SandboxRepairExecutor(verify)
    runs = [
        run_repair_case(fixture, success_case, planner, executor, retry_budget=1),
        run_repair_case(fixture, failure_case, planner, executor, retry_budget=1),
    ]
    metrics = summarize_repair_runs(runs)
    assert metrics.cases == 2
    assert metrics.repair_success_rate == 0.5
    assert metrics.first_attempt_success_rate == 0.5
    assert metrics.escalation_rate == 0.5
    assert metrics.mean_attempts == 1

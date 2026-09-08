from pathlib import Path

from ci_failure_orchestrator.agent_eval import ReplayAgentBackend, run_agent_case, summarize_agent_results
from ci_failure_orchestrator.repair import SandboxRepairExecutor


def test_replay_agent_runs_verified_repair(tmp_path: Path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "value.txt").write_text("BROKEN\n", encoding="utf-8")
    case = {
        "id": "agent-repair",
        "repair_candidates": [
            {"strategy": "replace_text", "target_path": "value.txt", "old": "BROKEN", "new": "FIXED"},
        ],
    }

    def verify(repo: Path):
        ok = (repo / "value.txt").read_text(encoding="utf-8").strip() == "FIXED"
        return ok, not ok, "", ""

    result = run_agent_case(
        fixture,
        case,
        ReplayAgentBackend(),
        SandboxRepairExecutor(verify),
        retry_budget=2,
    )
    assert result.resolved is True
    assert result.attempts == 1
    assert result.usage.model == "replay-agent-v1"
    assert result.usage.token_source == "estimated_replay"
    assert result.usage.cost_source == "no_external_model_call"


def test_agent_metrics_preserve_claim_scope(tmp_path: Path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "value.txt").write_text("BROKEN\n", encoding="utf-8")
    case = {
        "id": "agent-repair",
        "repair_candidates": [
            {"strategy": "replace_text", "target_path": "value.txt", "old": "BROKEN", "new": "FIXED"},
        ],
    }

    def verify(repo: Path):
        ok = "FIXED" in (repo / "value.txt").read_text(encoding="utf-8")
        return ok, not ok, "", ""

    result = run_agent_case(fixture, case, ReplayAgentBackend(), SandboxRepairExecutor(verify))
    metrics = summarize_agent_results([result])
    assert metrics.cases == 1
    assert metrics.repair_success_rate == 1.0
    assert metrics.total_tokens > 0
    assert metrics.total_cost_usd == 0.0
    assert metrics.cost_per_success_usd == 0.0

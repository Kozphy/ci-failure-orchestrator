"""LangGraph diagnosis flow: success, provider failure, timeout, and idempotent emit."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("langgraph")

from ci_failure_orchestrator.diagnosis_graph import (
    DiagnosisGraphRunner,
    MockHypothesisProvider,
)
from ci_failure_orchestrator.diagnosis_graph.graph import (
    build_diagnosis_graph,
    initial_state,
)
from ci_failure_orchestrator.foundation.models import FailureEvent, RunStatus
from ci_failure_orchestrator.foundation.persistence import RunPersistence
from ci_failure_orchestrator.server.settings import ServerSettings
from ci_failure_orchestrator.server.worker import default_foundation_factory


def _event(run_id: str = "run-diag-1", **overrides) -> FailureEvent:
    data = {
        "run_id": run_id,
        "workflow": "ci",
        "job": "test",
        "failed_step": "pytest",
        "message": "AssertionError: expected True got False",
        "log_excerpt": "FAILED tests/test_app.py::test_login - AssertionError",
        "changed_paths": ["src/app.py"],
    }
    data.update(overrides)
    return FailureEvent.from_dict(data, run_id=run_id)


def test_successful_execution_confirms_matching_hypothesis(tmp_path: Path):
    persistence = RunPersistence(tmp_path / "artifacts")
    runner = DiagnosisGraphRunner(
        tmp_path / "artifacts",
        persistence=persistence,
        provider=MockHypothesisProvider(category="test_failure"),
    )
    result = runner.run(_event())
    assert result.workflow_status == "DIAGNOSIS_CONFIRMED"
    assert result.status is RunStatus.SUCCEEDED
    assert result.run.classification is not None
    assert result.run.classification.category == "test_failure"
    assert result.technical_status == "PASS"
    assert len(runner.action_ledger) == 1
    decision = tmp_path / "artifacts" / "runs" / "run-diag-1" / "diagnosis" / "decision.json"
    assert decision.is_file()


def test_provider_hard_failure_does_not_confirm(tmp_path: Path):
    runner = DiagnosisGraphRunner(
        tmp_path / "artifacts",
        persistence=RunPersistence(tmp_path / "artifacts"),
        provider=MockHypothesisProvider(hard_fail=True),
    )
    result = runner.run(_event("run-hard"))
    assert result.workflow_status == "DIAGNOSIS_PROVIDER_FAILED"
    assert result.status is RunStatus.FAILED
    assert result.technical_status == "FAIL"
    assert len(runner.action_ledger) == 1


def test_provider_transient_failure_then_recovery(tmp_path: Path):
    provider = MockHypothesisProvider(category="test_failure", failures_before_success=2)
    runner = DiagnosisGraphRunner(
        tmp_path / "artifacts",
        persistence=RunPersistence(tmp_path / "artifacts"),
        provider=provider,
        max_provider_attempts=3,
    )
    result = runner.run(_event("run-retry"))
    assert result.workflow_status == "DIAGNOSIS_CONFIRMED"
    assert provider.calls == 3  # two transient failures, then success
    assert result.attempts == 3


def test_timeout_skips_hypothesis_and_fails(tmp_path: Path):
    runner = DiagnosisGraphRunner(
        tmp_path / "artifacts",
        persistence=RunPersistence(tmp_path / "artifacts"),
        provider=MockHypothesisProvider(delay_seconds=0.5, category="test_failure"),
        hypothesize_timeout_seconds=0.05,
    )
    result = runner.run(_event("run-timeout"))
    assert result.workflow_status == "DIAGNOSIS_TIMED_OUT"
    assert result.status is RunStatus.FAILED
    assert len(runner.action_ledger) == 1


def test_mismatched_hypothesis_escalates_without_trusting_model(tmp_path: Path):
    runner = DiagnosisGraphRunner(
        tmp_path / "artifacts",
        persistence=RunPersistence(tmp_path / "artifacts"),
        provider=MockHypothesisProvider(category="network_failure"),
    )
    result = runner.run(_event("run-mismatch"))
    assert result.workflow_status == "DIAGNOSIS_ESCALATED"
    assert result.status is RunStatus.AWAITING_HUMAN
    assert result.technical_status == "FAIL"


def test_resume_does_not_emit_duplicate_consequential_action(tmp_path: Path):
    emissions: list[str] = []

    def on_action(action_id: str, _state: dict) -> None:
        emissions.append(action_id)

    provider = MockHypothesisProvider(category="test_failure")
    graph = build_diagnosis_graph(provider=provider, on_action=on_action)
    event = _event("run-idempotent")
    config = {"configurable": {"thread_id": event.run_id}}
    first = graph.invoke(initial_state(event), config)
    assert first["action_emitted"] is True
    assert len(emissions) == 1
    # Second invoke with the same thread: emit must remain a no-op.
    second = graph.invoke(initial_state(event), config)
    assert second.get("consequential_action_id") == first["consequential_action_id"]
    assert len(emissions) == 1


def test_worker_factory_selects_diagnosis_graph(tmp_path: Path):
    settings = ServerSettings(
        database_url=f"sqlite:///{tmp_path / 'w.db'}",
        artifacts_root=tmp_path / "artifacts",
        execution_mode="diagnosis_graph",
    )
    persistence = RunPersistence(settings.artifacts_root)
    runner = default_foundation_factory(persistence, settings)
    assert isinstance(runner, DiagnosisGraphRunner)


def test_settings_reject_unknown_execution_mode():
    with pytest.raises(ValueError, match="CFO_EXECUTION_MODE"):
        ServerSettings.from_env({"CFO_EXECUTION_MODE": "magic"})

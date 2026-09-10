from __future__ import annotations

from pathlib import Path

import pytest

from ci_failure_orchestrator.autonomous_runtime import (
    AutonomousRuntime,
    DurableRunState,
    InvocationBudget,
    SQLiteRunStore,
)


def runtime(tmp_path: Path) -> AutonomousRuntime:
    store = SQLiteRunStore(tmp_path / "runtime.db")
    return AutonomousRuntime(
        store,
        budget=InvocationBudget(max_calls=2, max_tokens=100, max_cost_usd=1.0),
        approval_risk_threshold=0.6,
    )


def test_submit_persists_and_poll_leases_due_run(tmp_path: Path) -> None:
    rt = runtime(tmp_path)
    state = DurableRunState(run_id="run-1", incident_id="inc-1")

    rt.submit(state)
    leased = list(rt.poll(owner="worker-a", now=state.next_run_at + 1))

    assert len(leased) == 1
    assert leased[0].run_id == "run-1"
    assert leased[0].status == "running"
    assert leased[0].lease_owner == "worker-a"


def test_state_survives_store_reopen(tmp_path: Path) -> None:
    path = tmp_path / "runtime.db"
    store = SQLiteRunStore(path)
    store.save(DurableRunState(run_id="run-2", incident_id="inc-2", step="diagnosis"))

    reopened = SQLiteRunStore(path)
    loaded = reopened.load("run-2")

    assert loaded is not None
    assert loaded.step == "diagnosis"
    assert loaded.incident_id == "inc-2"


def test_retry_budget_exhaustion_moves_run_to_dlq(tmp_path: Path) -> None:
    store = SQLiteRunStore(tmp_path / "runtime.db")
    state = DurableRunState(run_id="run-3", incident_id="inc-3", max_attempts=2)
    store.save(state)

    store.mark_retry(state, error="first", backoff_seconds=0)
    assert store.load("run-3").status == "retry"  # type: ignore[union-attr]

    store.mark_retry(state, error="second", backoff_seconds=0)
    loaded = store.load("run-3")

    assert loaded is not None
    assert loaded.status == "dead_lettered"
    assert loaded.last_error == "retry_budget_exhausted"
    assert store.list_dead_letters()[0]["run_id"] == "run-3"


def test_ai_invocation_budget_is_hard_gate(tmp_path: Path) -> None:
    rt = runtime(tmp_path)
    state = DurableRunState(run_id="run-4", incident_id="inc-4")
    rt.submit(state)

    rt.record_ai_invocation(state, tokens=60, cost_usd=0.40)

    with pytest.raises(RuntimeError, match="budget exceeded"):
        rt.record_ai_invocation(state, tokens=50, cost_usd=0.20)


def test_approval_policy_covers_risk_production_and_destructive_changes(tmp_path: Path) -> None:
    rt = runtime(tmp_path)

    assert not rt.approval_required(risk_score=0.2)
    assert rt.approval_required(risk_score=0.7)
    assert rt.approval_required(risk_score=0.1, production_change=True)
    assert rt.approval_required(risk_score=0.1, destructive_change=True)


def test_complete_clears_lease_and_persists_terminal_state(tmp_path: Path) -> None:
    rt = runtime(tmp_path)
    state = DurableRunState(run_id="run-5", incident_id="inc-5", lease_owner="worker-a", lease_until=999)

    rt.complete(state)
    loaded = rt.store.load("run-5")

    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.step == "verified"
    assert loaded.lease_owner is None
    assert loaded.lease_until == 0.0

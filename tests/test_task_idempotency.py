"""Idempotent AgentTask delivery and durable completion ledger tests."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from ci_failure_orchestrator.github_repair_adapter import AgentTask, FailedCheck, build_repair_plan
from ci_failure_orchestrator.repair_state_machine import (
    RepairCoordinator,
    RepairIncident,
    RepairState,
    WorkerResult,
)
from ci_failure_orchestrator.supervisor import RepairAuthority
from ci_failure_orchestrator.task_idempotency import (
    DeliveryConflictError,
    IdempotentTaskDeliverer,
    SQLiteCompletionLedger,
    derive_idempotency_key,
)


def _task(key: str = "idem-key-1") -> AgentTask:
    return AgentTask(
        objective="fix lint",
        failure_class="lint",
        authority=RepairAuthority.AUTONOMOUS_PATCH,
        allowed_paths=("src/a.py",),
        required_gates=("targeted_tests",),
        forbidden_actions=("disable_required_checks",),
        evidence=("job=lint",),
        idempotency_key=key,
    )


def test_every_built_agent_task_has_idempotency_key() -> None:
    plan = build_repair_plan(
        FailedCheck("ci", "lint", "ruff", "ruff failed", ("src/a.py",))
    )
    assert plan.task is not None
    assert plan.task.idempotency_key
    assert len(plan.task.idempotency_key) == 64
    # Same logical identity → same key
    again = build_repair_plan(
        FailedCheck("ci", "lint", "ruff", "ruff failed", ("src/a.py",))
    )
    assert again.task is not None
    assert again.task.idempotency_key == plan.task.idempotency_key
    assert derive_idempotency_key("a", "b") == derive_idempotency_key("a", "b")


def test_duplicate_delivery_does_not_rerun_side_effect(tmp_path: Path) -> None:
    ledger = SQLiteCompletionLedger(tmp_path / "ledger.db")
    deliverer = IdempotentTaskDeliverer(ledger, worker_id="w1")
    calls: list[str] = []

    def side_effect(task: AgentTask) -> dict:
        calls.append(task.idempotency_key)
        return {"patch_id": "p1", "ok": True}

    task = _task()
    first = deliverer.deliver(task, side_effect)
    second = deliverer.deliver(task, side_effect)

    assert first.executed is True
    assert first.replayed is False
    assert second.executed is False
    assert second.replayed is True
    assert second.result == first.result
    assert calls == [task.idempotency_key]
    assert ledger.get_completed(task.idempotency_key) is not None


def test_concurrent_duplicate_delivery_executes_once(tmp_path: Path) -> None:
    ledger = SQLiteCompletionLedger(tmp_path / "ledger.db")
    task = _task("concurrent-key")
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []
    lock = threading.Lock()
    outcomes: list = []
    errors: list[BaseException] = []

    def side_effect(bound: AgentTask) -> dict:
        with lock:
            calls.append(1)
        started.set()
        assert release.wait(timeout=5), "side effect was not released"
        return {"n": 1}

    def winner() -> None:
        deliverer = IdempotentTaskDeliverer(ledger, worker_id="w-a", lease_seconds=30.0)
        try:
            outcomes.append(deliverer.deliver(task, side_effect))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def loser() -> None:
        deliverer = IdempotentTaskDeliverer(ledger, worker_id="w-b", lease_seconds=30.0)
        assert started.wait(timeout=5), "winner never claimed"
        try:
            outcomes.append(deliverer.deliver(task, side_effect))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            release.set()

    t1 = threading.Thread(target=winner)
    t2 = threading.Thread(target=loser)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert calls == [1]
    assert len(outcomes) == 1 and outcomes[0].executed is True
    assert len(errors) == 1 and isinstance(errors[0], DeliveryConflictError)
    # After winner completes, a later delivery must replay without executing.
    replay = IdempotentTaskDeliverer(ledger, worker_id="w-c").deliver(task, side_effect)
    assert replay.executed is False
    assert replay.replayed is True
    assert calls == [1]
    assert ledger.get_completed(task.idempotency_key) is not None


def test_worker_crash_then_redelivery_executes_side_effect_once(tmp_path: Path) -> None:
    ledger = SQLiteCompletionLedger(tmp_path / "ledger.db")
    task = _task("crash-key")
    calls: list[int] = []

    def exploding_side_effect(bound: AgentTask) -> dict:
        calls.append(1)
        raise RuntimeError("worker crashed mid-effect")

    def healthy_side_effect(bound: AgentTask) -> dict:
        calls.append(2)
        return {"recovered": True}

    crashed = IdempotentTaskDeliverer(ledger, worker_id="crasher", lease_seconds=30.0)
    with pytest.raises(RuntimeError, match="worker crashed"):
        crashed.deliver(task, exploding_side_effect)

    # Lease released on crash → redelivery may claim and execute once.
    recovered = IdempotentTaskDeliverer(ledger, worker_id="recovery", lease_seconds=30.0)
    outcome = recovered.deliver(task, healthy_side_effect)
    replay = recovered.deliver(task, healthy_side_effect)

    assert calls == [1, 2]
    assert outcome.executed is True
    assert outcome.result == {"recovered": True}
    assert replay.executed is False
    assert replay.replayed is True


def test_crash_after_completion_redelivery_replays_without_side_effect(tmp_path: Path) -> None:
    """Simulate: side effect + ledger complete succeeded; local process died after."""

    ledger = SQLiteCompletionLedger(tmp_path / "ledger.db")
    deliverer = IdempotentTaskDeliverer(ledger, worker_id="w1")
    task = _task("post-complete-crash")
    calls: list[str] = []

    def side_effect(bound: AgentTask) -> dict:
        calls.append("ran")
        return {"patch_proposed": True, "changed_paths": ["a.py"], "changed_lines": 1}

    first = deliverer.deliver(task, side_effect)
    # Process "crashes" after durable completion; queue redelivers.
    second = IdempotentTaskDeliverer(ledger, worker_id="w2").deliver(task, side_effect)

    assert first.executed is True
    assert second.executed is False
    assert second.replayed is True
    assert calls == ["ran"]


def test_coordinator_idempotent_delivery_integration(tmp_path: Path) -> None:
    ledger = SQLiteCompletionLedger(tmp_path / "ledger.db")
    deliverer = IdempotentTaskDeliverer(ledger, worker_id="coord-1")
    coordinator = RepairCoordinator()
    check = FailedCheck("ci", "lint", "ruff", "ruff failed", ("src/a.py",))
    incident = RepairIncident("inc-1", check)
    plan = coordinator.plan(incident)
    assert plan.task is not None
    assert incident.state is RepairState.PLANNED

    calls: list[str] = []

    def worker(task: AgentTask) -> WorkerResult:
        calls.append(task.idempotency_key)
        return WorkerResult(patch_proposed=True, changed_paths=("src/a.py",), changed_lines=2)

    first = coordinator.deliver_idempotent(incident, plan.task, worker, deliverer)
    second = coordinator.deliver_idempotent(incident, plan.task, worker, deliverer)

    assert first.executed is True
    assert second.executed is False
    assert second.replayed is True
    assert calls == [plan.task.idempotency_key]
    assert incident.state is RepairState.VERIFYING

from ci_failure_orchestrator.autonomous_runtime import DurableRunState, InvocationBudget, SQLiteRunStore
from ci_failure_orchestrator.distributed_runtime import (
    CallableEvaluationGate,
    InMemoryWorkQueue,
    MemoryTelemetry,
    ReliabilityRuntime,
    SLOPolicy,
)
from ci_failure_orchestrator.runtime_contracts import GateResult


def test_verified_run_requires_evaluation(tmp_path):
    store = SQLiteRunStore(tmp_path / "runtime.db")
    queue = InMemoryWorkQueue()
    telemetry = MemoryTelemetry()
    runtime = ReliabilityRuntime(
        store=store,
        queue=queue,
        evaluation_gate=CallableEvaluationGate(lambda state: GateResult(True, score=0.98)),
        telemetry=telemetry,
    )
    state = DurableRunState(run_id="r1", incident_id="i1")

    runtime.submit(state)
    result = runtime.finalize_candidate(state, latency_ms=25)

    assert result.passed
    assert store.load("r1").status == "verified"
    assert telemetry.counters["orchestrator.runs.verified"] == 1


def test_failed_evaluation_is_dead_lettered_and_replayable(tmp_path):
    store = SQLiteRunStore(tmp_path / "runtime.db")
    queue = InMemoryWorkQueue()
    runtime = ReliabilityRuntime(
        store=store,
        queue=queue,
        evaluation_gate=CallableEvaluationGate(
            lambda state: GateResult(False, score=0.2, reason="regression_detected")
        ),
    )
    state = DurableRunState(run_id="r2", incident_id="i2")

    runtime.submit(state)
    runtime.finalize_candidate(state, latency_ms=10)

    assert store.load("r2").status == "dead_lettered"
    assert queue.dead_letters["r2"] == "regression_detected"
    assert runtime.replay("r2") is True
    assert store.load("r2").status == "queued"


def test_ai_budget_is_enforced_before_more_work(tmp_path):
    store = SQLiteRunStore(tmp_path / "runtime.db")
    runtime = ReliabilityRuntime(
        store=store,
        queue=InMemoryWorkQueue(),
        evaluation_gate=CallableEvaluationGate(lambda state: GateResult(True)),
        budget=InvocationBudget(max_calls=1, max_tokens=100, max_cost_usd=0.10),
    )
    state = DurableRunState(run_id="r3", incident_id="i3")
    runtime.submit(state)
    runtime.reserve_ai(state, tokens=100, cost_usd=0.10)

    try:
        runtime.reserve_ai(state, tokens=1, cost_usd=0.0)
        raised = False
    except RuntimeError:
        raised = True

    assert raised


def test_slo_snapshot_detects_bad_dead_letter_rate(tmp_path):
    store = SQLiteRunStore(tmp_path / "runtime.db")
    runtime = ReliabilityRuntime(
        store=store,
        queue=InMemoryWorkQueue(),
        evaluation_gate=CallableEvaluationGate(lambda state: GateResult(False, reason="failed")),
    )
    state = DurableRunState(run_id="r4", incident_id="i4")
    runtime.submit(state)
    runtime.finalize_candidate(state, latency_ms=5)

    assert runtime.slo.passes(SLOPolicy(max_dead_letter_rate=0.0)) is False

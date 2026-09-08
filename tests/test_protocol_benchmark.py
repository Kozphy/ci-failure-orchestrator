from ci_failure_orchestrator.benchmark_suite import BenchmarkResult, BenchmarkSuite
from ci_failure_orchestrator.protocol import Decision, EvidenceEnvelope, FailureEnvelope, RepairEnvelope


def test_protocol_envelopes_are_provider_neutral_and_serializable():
    failure = FailureEnvelope.new(
        provider="github-actions",
        repository="org/repo",
        pipeline_run_id="123",
        stage="unit",
        failure_class="test",
        root_cause_confidence=0.91,
    )
    repair = RepairEnvelope.new(
        failure_id=failure.failure_id,
        agent="test-agent",
        strategy="minimal-patch",
        confidence=0.88,
        estimated_cost=0.04,
    )
    evidence = EvidenceEnvelope.new(
        failure_id=failure.failure_id,
        repair_id=repair.repair_id,
        decision=Decision.RELEASE,
        reason="independent verification passed",
        cumulative_cost=0.04,
        cumulative_latency_ms=800,
        attempt=1,
    )
    assert failure.to_dict()["provider"] == "github-actions"
    assert repair.to_dict()["failure_id"] == failure.failure_id
    assert evidence.to_dict()["decision"] == "release"


def test_benchmark_suite_reports_core_safety_metrics():
    summary = BenchmarkSuite.summarize([
        BenchmarkResult("a", True, True, False, False, 0, 0.1, 100),
        BenchmarkResult("b", False, True, True, False, 1, 0.2, 300),
        BenchmarkResult("c", True, False, False, True, 2, 0.0, 200),
    ])
    assert summary.cases == 3
    assert summary.root_cause_accuracy == 2 / 3
    assert summary.repair_success_rate == 2 / 3
    assert summary.false_repair_rate == 0.5
    assert summary.regression_rate == 1 / 3
    assert summary.escalation_rate == 1 / 3
    assert summary.mean_retries == 1
    assert summary.p50_latency_ms == 200

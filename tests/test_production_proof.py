from ci_failure_orchestrator.production_proof import (
    ProductionMetrics,
    ProductionPolicy,
    evaluate_production_gate,
)


def test_gate_passes_when_all_thresholds_are_met():
    metrics = ProductionMetrics(
        repair_success_rate=0.95,
        regression_rate=0.01,
        p95_latency_seconds=18.0,
        cost_per_success_usd=0.12,
        critical_security_findings=0,
    )
    result = evaluate_production_gate(metrics)
    assert result.passed is True
    assert result.decision == "PASS"
    assert all(result.checks.values())


def test_gate_blocks_regression_even_when_other_metrics_are_good():
    metrics = ProductionMetrics(
        repair_success_rate=0.98,
        regression_rate=0.08,
        p95_latency_seconds=10.0,
        cost_per_success_usd=0.05,
        critical_security_findings=0,
    )
    result = evaluate_production_gate(metrics)
    assert result.passed is False
    assert result.decision == "BLOCK"
    assert result.checks["regression_rate"] is False


def test_custom_policy_is_supported():
    policy = ProductionPolicy(min_repair_success_rate=0.75)
    metrics = ProductionMetrics(
        repair_success_rate=0.80,
        regression_rate=0.01,
        p95_latency_seconds=20.0,
        cost_per_success_usd=0.10,
    )
    assert evaluate_production_gate(metrics, policy).passed is True

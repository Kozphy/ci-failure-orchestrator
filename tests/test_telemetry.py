from ci_failure_orchestrator.telemetry import (
    MetricsRegistry,
    ProductionGateTarget,
    RepairRunObservation,
    evaluate_production_gate,
)


def test_registry_records_values() -> None:
    registry = MetricsRegistry()
    registry.inc("runs")
    registry.inc("runs", 2)
    registry.observe("latency_ms", 12.5)

    assert registry.counters["runs"] == 3
    assert registry.observations["latency_ms"] == [12.5]


def test_production_gate_passes_safe_window() -> None:
    observations = [
        RepairRunObservation(
            repository="example/repo",
            failure_class="dependency",
            action="READY_FOR_POLICY_GATE",
            attempts=1,
            success=True,
            latency_seconds=30 + index,
        )
        for index in range(20)
    ]

    report = evaluate_production_gate(observations)

    assert report.passed is True
    assert report.success_rate == 1.0
    assert report.false_repair_rate == 0.0
    assert report.regression_rate == 0.0


def test_production_gate_blocks_false_repairs_and_regressions() -> None:
    observations = [
        RepairRunObservation(
            repository="example/repo",
            failure_class="test",
            action="READY_FOR_POLICY_GATE",
            attempts=2,
            success=False,
            latency_seconds=400,
            regression_detected=True,
        ),
        RepairRunObservation(
            repository="example/repo",
            failure_class="lint",
            action="ESCALATE_HUMAN",
            attempts=3,
            success=False,
            latency_seconds=100,
            human_escalated=True,
        ),
    ]

    report = evaluate_production_gate(
        observations,
        target=ProductionGateTarget(
            minimum_success_rate=0.8,
            maximum_false_repair_rate=0.1,
            maximum_regression_rate=0.1,
            maximum_p95_latency_seconds=200,
            maximum_human_escalation_rate=0.2,
        ),
    )

    assert report.passed is False
    assert "success rate below target" in report.violations
    assert "false repair rate above target" in report.violations
    assert "regression rate above target" in report.violations
    assert "p95 latency above target" in report.violations
    assert "human escalation rate above target" in report.violations


def test_production_gate_rejects_empty_evidence() -> None:
    report = evaluate_production_gate([])

    assert report.passed is False
    assert report.observations == 0
    assert "no observations available" in report.violations

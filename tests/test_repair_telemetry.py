import pytest

from ci_failure_orchestrator.repair_telemetry import (
    RepairObservation,
    aggregate_metrics,
    group_metrics_by_provider,
)


def test_aggregate_metrics_tracks_quality_cost_and_latency() -> None:
    metrics = aggregate_metrics(
        (
            RepairObservation("a", "w1", True, False, 0.4, 1000, 1),
            RepairObservation("a", "w1", False, True, 0.2, 3000, 2),
            RepairObservation("a", "w2", True, False, 0.6, 2000, 1),
        )
    )
    assert metrics.total == 3
    assert metrics.successes == 2
    assert metrics.false_repairs == 1
    assert metrics.success_rate == pytest.approx(2 / 3)
    assert metrics.false_repair_rate == pytest.approx(1 / 3)
    assert metrics.cost_per_success_usd == pytest.approx(0.6)
    assert metrics.p95_latency_ms == 3000


def test_group_metrics_by_provider_isolated() -> None:
    grouped = group_metrics_by_provider(
        (
            RepairObservation("a", "w1", True, False, 0.1, 100, 1),
            RepairObservation("b", "w2", False, False, 0.2, 200, 2),
        )
    )
    assert grouped["a"].success_rate == 1.0
    assert grouped["b"].success_rate == 0.0
    assert grouped["b"].cost_per_success_usd is None


def test_empty_metrics_are_well_defined() -> None:
    metrics = aggregate_metrics(())
    assert metrics.total == 0
    assert metrics.p95_latency_ms == 0
    assert metrics.cost_per_success_usd is None

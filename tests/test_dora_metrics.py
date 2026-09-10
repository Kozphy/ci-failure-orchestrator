from datetime import datetime, timedelta, timezone

import pytest

from ci_failure_orchestrator.dora_metrics import DeploymentEvent, calculate_dora_metrics


def ts(hour: int) -> datetime:
    return datetime(2026, 9, 10, hour, tzinfo=timezone.utc)


def test_dora_metrics_include_failure_and_recovery() -> None:
    events = [
        DeploymentEvent("d1", "a" * 40, ts(1), ts(2), True),
        DeploymentEvent("d2", "b" * 40, ts(3), ts(4), False, True, ts(5)),
        DeploymentEvent("d3", "c" * 40, ts(6), ts(7), True),
    ]

    metrics = calculate_dora_metrics(events)

    assert metrics.deployment_count == 3
    assert metrics.successful_deployments == 2
    assert metrics.failed_deployments == 1
    assert metrics.change_fail_rate == pytest.approx(1 / 3)
    assert metrics.rollback_rate == pytest.approx(1 / 3)
    assert metrics.median_lead_time_seconds == 3600
    assert metrics.median_recovery_time_seconds == 3600


def test_empty_deployment_history_is_rejected() -> None:
    with pytest.raises(ValueError):
        calculate_dora_metrics([])

from __future__ import annotations

import json
from pathlib import Path

from ci_failure_orchestrator.service import compute_operational_metrics, load_run_measurements


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _run(root: Path, run_id: str, *, category: str, summary: dict | None, classified: bool = True) -> None:
    run = root / "runs" / run_id
    _write(run / "input" / "failure-event.json", {"timestamp": "2026-10-01T09:00:00+00:00"})
    if classified:
        _write(
            run / "classification" / "classification.json",
            {"category": category, "timestamp": "2026-10-01T09:00:02+00:00"},
        )
    if summary is not None:
        _write(run / "metrics-summary.json", summary)


def test_operational_metrics_are_measured_from_stored_runs(tmp_path):
    _run(tmp_path, "run-a", category="test_failure",
         summary={"source": "runtime", "attempts": 1, "retries": 0, "duration_seconds": 4.0, "escalated": False})
    _run(tmp_path, "run-b", category="unknown",
         summary={"source": "runtime", "attempts": 3, "retries": 2, "duration_seconds": 8.0, "escalated": True})
    _run(tmp_path, "run-bench", category="test_failure",
         summary={"source": "benchmark", "attempts": 9, "retries": 8, "duration_seconds": 99.0, "escalated": True})

    metrics = compute_operational_metrics(load_run_measurements(tmp_path))

    assert metrics["failures_ingested"] == 2
    assert metrics["classified_rate"] == 0.5
    assert metrics["mean_time_to_diagnosis_seconds"] == 2.0
    assert metrics["mean_attempts_per_failure"] == 2.0
    assert metrics["mean_retries_per_failure"] == 1.0
    assert metrics["mean_compute_seconds_per_failure"] == 6.0
    assert metrics["escalation_rate"] == 0.5
    assert metrics["model_cost_per_repair"] is None
    assert metrics["definitions"]["model_cost_per_repair"].startswith("not instrumented")


def test_missing_measurements_are_none_not_zero(tmp_path):
    _run(tmp_path, "run-a", category="test_failure", summary=None, classified=False)

    metrics = compute_operational_metrics(load_run_measurements(tmp_path))

    assert metrics["failures_ingested"] == 1
    assert metrics["classified_rate"] == 0.0
    for key in ("mean_time_to_diagnosis_seconds", "mean_attempts_per_failure",
                "mean_compute_seconds_per_failure", "escalation_rate"):
        assert metrics[key] is None, key


def test_empty_artifacts_report_no_rates(tmp_path):
    metrics = compute_operational_metrics(load_run_measurements(tmp_path))
    assert metrics["failures_ingested"] == 0
    assert metrics["classified_rate"] is None

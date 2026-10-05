"""Repair outcome metrics over stored remediation records.

The primary metric is the Verified Repair Rate: VERIFIED_FIXED repairs divided by attempted
repairs. The CI Green Rate is reported next to it only to show how far apart "green" and
"verified" are; it is never a success measure on its own.

``ci_green`` means the configured checks passed: the real CI result once
``fix-repo-verify-ci`` has recorded one, otherwise the local sandbox verify commands.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..foundation.remediation import RemediationState
from .common import FIX_DIR, REMEDIATION_NAME

_FALSE_REPAIR_STATES = frozenset({
    RemediationState.POLICY_REJECTED.value,
    RemediationState.REGRESSION_DETECTED.value,
    RemediationState.NOT_FIXED.value,
})


def load_remediation_records(artifacts_root: Path) -> list[dict[str, Any]]:
    """Load every stored remediation record, skipping unreadable or malformed files."""
    records: list[dict[str, Any]] = []
    for path in sorted((Path(artifacts_root) / "runs").glob(f"*/{FIX_DIR}/{REMEDIATION_NAME}")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_run_measurements(artifacts_root: Path) -> list[dict[str, Any]]:
    """Per-run timestamps and counters for every ingested failure, excluding benchmark runs.

    Each item holds ``received_at`` (failure ingestion), ``classified_at``, ``category`` and,
    when the run wrote ``metrics-summary.json``, ``attempts``, ``retries``,
    ``duration_seconds`` and ``escalated``.
    """
    measurements: list[dict[str, Any]] = []
    for event_path in sorted((Path(artifacts_root) / "runs").glob("*/input/failure-event.json")):
        run_root = event_path.parent.parent
        summary = _read_json(run_root / "metrics-summary.json")
        if summary.get("source") == "benchmark":
            continue
        classification = _read_json(run_root / "classification" / "classification.json")
        measurements.append({
            "run_id": run_root.name,
            "received_at": _read_json(event_path).get("timestamp"),
            "classified_at": classification.get("timestamp"),
            "category": classification.get("category"),
            "has_summary": bool(summary),
            "attempts": summary.get("attempts"),
            "retries": summary.get("retries"),
            "duration_seconds": summary.get("duration_seconds"),
            "escalated": summary.get("escalated"),
        })
    return measurements


def compute_operational_metrics(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Diagnosis, retry, compute and escalation measures over ingested failures.

    Averages and rates are None when nothing was measured. Model cost is reported as not
    instrumented instead of estimated.
    """
    runs = list(runs)
    classified = [r for r in runs if r.get("classified_at")]
    summarized = [r for r in runs if r.get("has_summary")]

    def mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 3) if values else None

    diagnosis = [
        d for r in classified
        if (d := _seconds(str(r.get("received_at") or ""), str(r.get("classified_at") or ""))) is not None
    ]
    return {
        "failures_ingested": len(runs),
        "classified_rate": (
            round(sum(1 for r in classified if r.get("category") not in (None, "unknown")) / len(runs), 4)
            if runs else None
        ),
        "mean_time_to_diagnosis_seconds": mean(diagnosis),
        "mean_attempts_per_failure": mean([float(r["attempts"]) for r in summarized if r.get("attempts") is not None]),
        "mean_retries_per_failure": mean([float(r["retries"]) for r in summarized if r.get("retries") is not None]),
        "mean_compute_seconds_per_failure": mean(
            [float(r["duration_seconds"]) for r in summarized if r.get("duration_seconds") is not None]
        ),
        "escalation_rate": (
            round(sum(1 for r in summarized if r.get("escalated")) / len(summarized), 4) if summarized else None
        ),
        "model_cost_per_repair": None,
        "definitions": {
            "failures_ingested": "runs with a stored failure event (benchmark runs excluded)",
            "classified_rate": "runs classified into a known category (not 'unknown') / failures ingested",
            "mean_time_to_diagnosis_seconds": (
                "failure ingestion to classification; the CI failure time itself is not recorded"
            ),
            "mean_attempts_per_failure": "repair attempts per run that wrote a metrics summary",
            "mean_retries_per_failure": "attempts after the first, per run that wrote a metrics summary",
            "mean_compute_seconds_per_failure": "wall-clock orchestration time per run, including sandbox commands",
            "escalation_rate": "runs that ended escalated to a human / runs that wrote a metrics summary",
            "model_cost_per_repair": "not instrumented: provider commands do not report token usage or cost",
        },
    }


def _seconds(start: str, end: str) -> float | None:
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return None


def compute_remediation_metrics(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compute repair outcome rates over the records that attempted a repair.

    Each rate is None when its denominator is zero. The returned dict includes a
    ``definitions`` entry describing every metric.
    """
    attempted = [r for r in records if r.get("repair_attempted")]
    total = len(attempted)
    states = Counter(str(r.get("state")) for r in attempted)
    green = [r for r in attempted if r.get("ci_green")]

    def rate(count: int, of: int) -> float | None:
        return round(count / of, 4) if of else None

    durations = [
        d
        for r in attempted
        if r.get("state") == RemediationState.VERIFIED_FIXED.value
        and (d := _seconds(str(r.get("failure_received_at") or ""), str(r.get("decided_at") or ""))) is not None
    ]
    return {
        "primary_metric": "verified_repair_rate",
        "attempted_repairs": total,
        "verified_repair_rate": rate(states[RemediationState.VERIFIED_FIXED.value], total),
        "ci_green_rate": rate(len(green), total),
        "false_repair_rate": rate(sum(1 for r in green if r.get("state") in _FALSE_REPAIR_STATES), len(green)),
        "regression_rate": rate(states[RemediationState.REGRESSION_DETECTED.value], total),
        "policy_rejection_rate": rate(states[RemediationState.POLICY_REJECTED.value], total),
        "human_escalation_rate": rate(states[RemediationState.HUMAN_REVIEW_REQUIRED.value], total),
        "mean_time_to_verified_repair_seconds": round(sum(durations) / len(durations), 1) if durations else None,
        "states": dict(sorted(states.items())),
        "definitions": {
            "verified_repair_rate": "VERIFIED_FIXED / attempted repairs",
            "operational": "per-run diagnosis, retry, compute and escalation measures; see operational.definitions",
            "ci_green_rate": "repairs whose configured checks passed / attempted repairs (not a success measure)",
            "false_repair_rate": "CI-green repairs later rejected, regressed or not fixed / CI-green repairs",
            "regression_rate": "REGRESSION_DETECTED / attempted repairs",
            "policy_rejection_rate": "POLICY_REJECTED / attempted repairs",
            "human_escalation_rate": "HUMAN_REVIEW_REQUIRED / attempted repairs",
            "mean_time_to_verified_repair_seconds": "failure received to VERIFIED_FIXED decision",
        },
    }

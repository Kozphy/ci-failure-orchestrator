"""Executive overview metrics from local artifacts only.

CI-wide run counts and failure rates require a ``ci-audit.export.v1`` file. Without one
those fields stay ``None`` and ``unavailable`` explains why. Repair rates reuse the
existing remediation and operational loaders; they are not redefined here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..ci_audit import EXPORT_SCHEMA, analyze_export
from ..foundation.remediation import RemediationState
from ..service.remediation_metrics import (
    compute_operational_metrics,
    compute_remediation_metrics,
    load_remediation_records,
    load_run_measurements,
)
from .catalog import catalog_runs


@dataclass(frozen=True)
class OverviewMetrics:
    """Executive numbers. ``None`` means not available from the supplied evidence."""

    total_ci_runs: int | None
    failed_ci_runs: int | None
    ci_failure_rate: float | None
    verified_repair_rate: float | None
    policy_rejection_rate: float | None
    human_review_required_rate: float | None
    evidence_completeness_rate: float | None
    average_verification_duration_seconds: float | None
    attempted_repairs: int
    verified_fixed_count: int
    human_review_required_count: int
    policy_rejected_count: int
    catalog_run_count: int
    unavailable: dict[str, str] = field(default_factory=dict)
    definitions: dict[str, str] = field(default_factory=dict)
    evidence_class: str = "local_artifacts"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_DEFINITIONS = {
    "total_ci_runs": "completed runs in a supplied ci-audit.export.v1; otherwise N/A",
    "failed_ci_runs": "failed completed runs in that export; otherwise N/A",
    "ci_failure_rate": "failed / decided completed runs from the export; otherwise N/A",
    "verified_repair_rate": "VERIFIED_FIXED / attempted repairs from remediation.json files",
    "policy_rejection_rate": "POLICY_REJECTED / attempted repairs",
    "human_review_required_rate": "HUMAN_REVIEW_REQUIRED / attempted repairs",
    "evidence_completeness_rate": (
        "among runs with evidence-report.json, share whose remaining_risks list is empty"
    ),
    "average_verification_duration_seconds": (
        "mean seconds from failure_received_at to decided_at for VERIFIED_FIXED repairs; "
        "falls back to mean orchestration duration when no verified duration exists"
    ),
}


def _audit_totals(export_path: Path | None) -> tuple[int | None, int | None, float | None, str | None]:
    if export_path is None:
        return None, None, None, "no ci-audit export supplied; local repair artifacts are not a CI history"
    try:
        payload = json.loads(export_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None, None, "ci-audit export could not be read as JSON"
    if not isinstance(payload, dict) or payload.get("schema") != EXPORT_SCHEMA:
        return None, None, None, f"export schema must be {EXPORT_SCHEMA}"
    try:
        analysis = analyze_export(payload)
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        return None, None, None, f"export could not be analyzed: {exc}"
    totals = analysis.get("totals") or {}
    completed = totals.get("completed")
    failed = totals.get("failed")
    rate = totals.get("failure_rate")
    if not isinstance(completed, int) or not isinstance(failed, int):
        return None, None, None, "export analysis lacked completed/failed totals"
    return completed, failed, float(rate) if isinstance(rate, (int, float)) else None, None


def _evidence_completeness(artifacts_root: Path) -> float | None:
    rows = [row for row in catalog_runs(artifacts_root) if row.has_evidence_report]
    if not rows:
        return None
    complete = sum(1 for row in rows if row.remaining_risk_count == 0)
    return round(complete / len(rows), 4)


def build_overview_metrics(
    artifacts_root: Path,
    *,
    ci_audit_export: Path | None = None,
) -> OverviewMetrics:
    """Aggregate executive metrics. Does not invent CI history from repair runs alone."""
    unavailable: dict[str, str] = {}
    total, failed, failure_rate, audit_reason = _audit_totals(ci_audit_export)
    if audit_reason:
        unavailable["total_ci_runs"] = audit_reason
        unavailable["failed_ci_runs"] = audit_reason
        unavailable["ci_failure_rate"] = audit_reason

    records = load_remediation_records(artifacts_root)
    remediation = compute_remediation_metrics(records)
    operational = compute_operational_metrics(load_run_measurements(artifacts_root))
    states = remediation.get("states") or {}
    verified_count = int(states.get(RemediationState.VERIFIED_FIXED.value, 0))
    human_count = int(states.get(RemediationState.HUMAN_REVIEW_REQUIRED.value, 0))
    rejected_count = int(states.get(RemediationState.POLICY_REJECTED.value, 0))

    completeness = _evidence_completeness(artifacts_root)
    if completeness is None:
        unavailable["evidence_completeness_rate"] = "no evidence-report.json files under runs/*/fix-repo/"

    duration = remediation.get("mean_time_to_verified_repair_seconds")
    if duration is None:
        duration = operational.get("mean_compute_seconds_per_failure")
        if duration is None:
            unavailable["average_verification_duration_seconds"] = (
                "no VERIFIED_FIXED durations and no metrics-summary durations"
            )
        else:
            unavailable["average_verification_duration_seconds"] = (
                "no VERIFIED_FIXED duration; using mean orchestration duration from metrics-summary.json"
            )

    if remediation.get("verified_repair_rate") is None:
        unavailable["verified_repair_rate"] = "no attempted repairs with remediation.json"
    if remediation.get("policy_rejection_rate") is None:
        unavailable["policy_rejection_rate"] = "no attempted repairs with remediation.json"
    if remediation.get("human_escalation_rate") is None:
        unavailable["human_review_required_rate"] = "no attempted repairs with remediation.json"

    return OverviewMetrics(
        total_ci_runs=total,
        failed_ci_runs=failed,
        ci_failure_rate=failure_rate,
        verified_repair_rate=remediation.get("verified_repair_rate"),
        policy_rejection_rate=remediation.get("policy_rejection_rate"),
        human_review_required_rate=remediation.get("human_escalation_rate"),
        evidence_completeness_rate=completeness,
        average_verification_duration_seconds=(
            float(duration) if isinstance(duration, (int, float)) else None
        ),
        attempted_repairs=int(remediation.get("attempted_repairs") or 0),
        verified_fixed_count=verified_count,
        human_review_required_count=human_count,
        policy_rejected_count=rejected_count,
        catalog_run_count=len(catalog_runs(artifacts_root)),
        unavailable=unavailable,
        definitions=dict(_DEFINITIONS),
        evidence_class="local_artifacts_plus_optional_ci_audit_export"
        if ci_audit_export is not None
        else "local_artifacts",
    )

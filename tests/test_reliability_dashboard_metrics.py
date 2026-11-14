"""Tests for the read-only reliability dashboard metrics foundation."""

from __future__ import annotations

import json
from pathlib import Path

from ci_failure_orchestrator.ci_audit import EXPORT_SCHEMA
from ci_failure_orchestrator.foundation.remediation import RemediationState
from ci_failure_orchestrator.reliability_dashboard import (
    build_overview_metrics,
    catalog_runs,
    verify_run_integrity,
)
from ci_failure_orchestrator.service.common import FIX_DIR, REMEDIATION_NAME
from ci_failure_orchestrator.service.evidence_report import EVIDENCE_REPORT_JSON, EVIDENCE_REPORT_SCHEMA


def _write_run(
    artifacts: Path,
    run_id: str,
    *,
    state: str,
    remaining_risks: list[str] | None = None,
    repair_attempted: bool = True,
    repository: str = "o/r",
) -> None:
    root = artifacts / "runs" / run_id
    (root / "input").mkdir(parents=True)
    (root / FIX_DIR).mkdir(parents=True)
    (root / "classification").mkdir(parents=True)
    (root / "input" / "failure-event.json").write_text(
        json.dumps({"repository": repository, "commit_sha": "abc123", "timestamp": "2026-11-01T10:00:00"}),
        encoding="utf-8",
    )
    (root / "classification" / "classification.json").write_text(
        json.dumps({"category": "test_failure", "timestamp": "2026-11-01T10:00:01"}),
        encoding="utf-8",
    )
    (root / FIX_DIR / REMEDIATION_NAME).write_text(
        json.dumps(
            {
                "state": state,
                "repair_attempted": repair_attempted,
                "failure_received_at": "2026-11-01T10:00:00",
                "decided_at": "2026-11-01T10:05:00",
                "ci_green": state == RemediationState.VERIFIED_FIXED.value,
            }
        ),
        encoding="utf-8",
    )
    if remaining_risks is not None:
        risks = remaining_risks
    elif state == RemediationState.VERIFIED_FIXED.value:
        risks = []
    else:
        risks = ["regression suite"]
    (root / FIX_DIR / EVIDENCE_REPORT_JSON).write_text(
        json.dumps(
            {
                "schema": EVIDENCE_REPORT_SCHEMA,
                "run_id": run_id,
                "what_broke": {"repository": repository},
                "remaining_risks": risks,
                "outcome": {"policy": "ELIGIBLE", "verified": state == RemediationState.VERIFIED_FIXED.value},
            }
        ),
        encoding="utf-8",
    )


def test_overview_marks_ci_history_unavailable_without_export(tmp_path: Path):
    metrics = build_overview_metrics(tmp_path)
    assert metrics.total_ci_runs is None
    assert metrics.failed_ci_runs is None
    assert metrics.ci_failure_rate is None
    assert metrics.verified_repair_rate is None
    assert "total_ci_runs" in metrics.unavailable
    assert metrics.attempted_repairs == 0
    assert metrics.catalog_run_count == 0


def test_overview_uses_ci_audit_export_and_remediation_rates(tmp_path: Path):
    _write_run(tmp_path, "run-ok", state=RemediationState.VERIFIED_FIXED.value, remaining_risks=[])
    _write_run(tmp_path, "run-reject", state=RemediationState.POLICY_REJECTED.value)
    _write_run(tmp_path, "run-human", state=RemediationState.HUMAN_REVIEW_REQUIRED.value)
    export = tmp_path / "export.json"
    export.write_text(
        json.dumps(
            {
                "schema": EXPORT_SCHEMA,
                "repository": "o/r",
                "private": False,
                "since": "2026-09-01T00:00:00Z",
                "collected_at": "2026-09-30T00:00:00Z",
                "window_days": 30,
                "runs": [
                    {
                        "id": 1,
                        "workflow_id": 9,
                        "name": "ci",
                        "head_sha": "abc",
                        "html_url": "https://example.test/1",
                        "status": "completed",
                        "conclusion": "success",
                        "run_attempt": 1,
                        "created_at": "2026-09-20T10:00:00Z",
                        "run_started_at": "2026-09-20T10:01:00Z",
                        "updated_at": "2026-09-20T10:02:00Z",
                    },
                    {
                        "id": 2,
                        "workflow_id": 9,
                        "name": "ci",
                        "head_sha": "def",
                        "html_url": "https://example.test/2",
                        "status": "completed",
                        "conclusion": "failure",
                        "run_attempt": 1,
                        "created_at": "2026-09-21T10:00:00Z",
                        "run_started_at": "2026-09-21T10:01:00Z",
                        "updated_at": "2026-09-21T10:02:00Z",
                    },
                ],
                "jobs": [],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    metrics = build_overview_metrics(tmp_path, ci_audit_export=export)
    assert metrics.total_ci_runs == 2
    assert metrics.failed_ci_runs == 1
    assert metrics.ci_failure_rate == 0.5
    assert metrics.attempted_repairs == 3
    assert metrics.verified_repair_rate == round(1 / 3, 4)
    assert metrics.policy_rejection_rate == round(1 / 3, 4)
    assert metrics.human_review_required_rate == round(1 / 3, 4)
    assert metrics.verified_fixed_count == 1
    assert metrics.evidence_completeness_rate == round(1 / 3, 4)
    assert metrics.average_verification_duration_seconds == 300.0


def test_catalog_skips_invalid_run_ids_and_redacts_secrets(tmp_path: Path):
    _write_run(tmp_path, "good-run", state=RemediationState.POLICY_APPROVED.value, repository="acme/app")
    (tmp_path / "runs" / "../escape").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs" / "bad id").mkdir(parents=True)
    rows = catalog_runs(tmp_path)
    assert [row.run_id for row in rows] == ["good-run"]
    assert rows[0].verification_state == RemediationState.POLICY_APPROVED.value
    assert rows[0].repository == "acme/app"
    assert rows[0].integrity_status == "unchecked"


def test_integrity_detects_missing_altered_and_ok(tmp_path: Path):
    _write_run(tmp_path, "run-1", state=RemediationState.VERIFIED_FIXED.value, remaining_risks=[])
    first = verify_run_integrity(tmp_path, "run-1")
    assert first.status in {"ok", "partial"}
    expected = {
        item.relative_path: item.file_sha256
        for item in first.files
        if item.present and item.file_sha256
    }
    assert verify_run_integrity(tmp_path, "run-1", expected_file_sha256=expected).status in {"ok", "partial"}
    target = tmp_path / "runs" / "run-1" / FIX_DIR / EVIDENCE_REPORT_JSON
    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
    altered = verify_run_integrity(tmp_path, "run-1", expected_file_sha256=expected)
    assert altered.status == "hash_mismatch"
    assert f"{FIX_DIR}/{EVIDENCE_REPORT_JSON}" in altered.mismatches
    missing = verify_run_integrity(tmp_path, "no-such-run")
    assert missing.status == "missing_run"


def test_malformed_remediation_is_skipped_by_metrics(tmp_path: Path):
    root = tmp_path / "runs" / "broken" / FIX_DIR
    root.mkdir(parents=True)
    (root / REMEDIATION_NAME).write_text("{not-json", encoding="utf-8")
    metrics = build_overview_metrics(tmp_path)
    assert metrics.attempted_repairs == 0
    assert metrics.verified_repair_rate is None


def test_policy_approved_is_not_counted_as_verified_fixed(tmp_path: Path):
    _write_run(tmp_path, "local-only", state=RemediationState.POLICY_APPROVED.value)
    metrics = build_overview_metrics(tmp_path)
    assert metrics.verified_fixed_count == 0
    assert metrics.verified_repair_rate == 0.0
    assert metrics.attempted_repairs == 1

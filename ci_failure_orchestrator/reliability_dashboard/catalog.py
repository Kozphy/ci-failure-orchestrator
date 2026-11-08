"""Catalog local repair-run artifacts for the evidence explorer foundation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..foundation.sanitization import sanitize_text
from ..service.common import FIX_DIR, REMEDIATION_NAME
from ..service.evidence_report import EVIDENCE_REPORT_JSON

_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_MAX_FIELD = 2_000


def _clip(value: Any) -> str:
    text = "" if value is None else str(value)
    cleaned, _ = sanitize_text(text)
    if len(cleaned) > _MAX_FIELD:
        return cleaned[:_MAX_FIELD] + "…[truncated]"
    return cleaned


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class RunEvidenceRow:
    """One run as seen on disk. Missing fields stay empty rather than invented."""

    run_id: str
    repository: str
    commit_sha: str
    failure_classification: str
    policy_decision: str
    verification_state: str
    evidence_manifest: str
    integrity_status: str
    timestamp: str
    has_evidence_report: bool
    has_remediation: bool
    remaining_risk_count: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def catalog_runs(artifacts_root: Path) -> list[RunEvidenceRow]:
    """Index ``runs/<id>/`` under ``artifacts_root``. Ignores invalid directory names."""
    root = Path(artifacts_root) / "runs"
    if not root.is_dir():
        return []
    rows: list[RunEvidenceRow] = []
    for run_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if not _RUN_ID.fullmatch(run_dir.name):
            continue
        event = _read_json(run_dir / "input" / "failure-event.json")
        classification = _read_json(run_dir / "classification" / "classification.json")
        remediation = _read_json(run_dir / FIX_DIR / REMEDIATION_NAME)
        policy = _read_json(run_dir / "policy" / "policy-decision.json")
        report = _read_json(run_dir / FIX_DIR / EVIDENCE_REPORT_JSON)
        what_broke = report.get("what_broke") if isinstance(report.get("what_broke"), dict) else {}
        outcome = report.get("outcome") if isinstance(report.get("outcome"), dict) else {}
        remaining = report.get("remaining_risks") if isinstance(report.get("remaining_risks"), list) else None
        evidence_path = run_dir / FIX_DIR / EVIDENCE_REPORT_JSON
        repository = event.get("repository") or what_broke.get("repository") or ""
        policy_decision = policy.get("outcome") or outcome.get("policy") or ""
        rows.append(
            RunEvidenceRow(
                run_id=run_dir.name,
                repository=_clip(repository),
                commit_sha=_clip(event.get("commit_sha") or ""),
                failure_classification=_clip(
                    classification.get("category") or remediation.get("failure_class") or ""
                ),
                policy_decision=_clip(policy_decision),
                verification_state=_clip(remediation.get("state") or ""),
                evidence_manifest=_clip(
                    str(evidence_path.relative_to(Path(artifacts_root))) if evidence_path.is_file() else ""
                ),
                integrity_status="unchecked",
                timestamp=_clip(remediation.get("decided_at") or event.get("timestamp") or ""),
                has_evidence_report=evidence_path.is_file(),
                has_remediation=(run_dir / FIX_DIR / REMEDIATION_NAME).is_file(),
                remaining_risk_count=len(remaining) if remaining is not None else None,
            )
        )
    return rows

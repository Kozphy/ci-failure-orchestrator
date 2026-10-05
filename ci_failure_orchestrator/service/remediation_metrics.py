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
            "ci_green_rate": "repairs whose configured checks passed / attempted repairs (not a success measure)",
            "false_repair_rate": "CI-green repairs later rejected, regressed or not fixed / CI-green repairs",
            "regression_rate": "REGRESSION_DETECTED / attempted repairs",
            "policy_rejection_rate": "POLICY_REJECTED / attempted repairs",
            "human_escalation_rate": "HUMAN_REVIEW_REQUIRED / attempted repairs",
            "mean_time_to_verified_repair_seconds": "failure received to VERIFIED_FIXED decision",
        },
    }

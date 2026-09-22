"""Baseline storage and regression comparison."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .schemas import SUITE_VERSION, BenchmarkCaseResult


class RegressionLabel(str, Enum):
    REGRESSED = "REGRESSED"
    IMPROVED = "IMPROVED"
    UNCHANGED_PASS = "UNCHANGED_PASS"
    UNCHANGED_FAIL = "UNCHANGED_FAIL"
    NEW_CASE = "NEW_CASE"
    REMOVED_CASE = "REMOVED_CASE"


@dataclass
class CaseDelta:
    case_id: str
    label: RegressionLabel
    baseline_passed: bool | None
    current_passed: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "label": self.label.value,
            "baseline_passed": self.baseline_passed,
            "current_passed": self.current_passed,
        }


class BaselineStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(
        self,
        results: list[BenchmarkCaseResult],
        *,
        metrics: dict[str, Any] | None = None,
        suite_version: str = SUITE_VERSION,
    ) -> dict[str, Any]:
        payload = {
            "suite_version": suite_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cases": {
                r.case_id: {
                    "passed": r.passed,
                    "required": r.required,
                    "category": r.category,
                }
                for r in results
            },
            "metrics": metrics or {},
            "implementation": {"package": "ci_failure_orchestrator.foundation"},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return payload


def compare_to_baseline(
    results: list[BenchmarkCaseResult],
    baseline: dict[str, Any] | None,
) -> list[CaseDelta]:
    current = {r.case_id: r.passed for r in results}
    previous = {}
    if baseline and isinstance(baseline.get("cases"), dict):
        for cid, info in baseline["cases"].items():
            if isinstance(info, dict):
                previous[cid] = bool(info.get("passed"))
            else:
                previous[cid] = bool(info)

    deltas: list[CaseDelta] = []
    all_ids = sorted(set(current) | set(previous))
    for cid in all_ids:
        cur = current.get(cid)
        prev = previous.get(cid)
        if prev is None and cur is not None:
            label = RegressionLabel.NEW_CASE
        elif cur is None and prev is not None:
            label = RegressionLabel.REMOVED_CASE
        elif prev is True and cur is False:
            label = RegressionLabel.REGRESSED
        elif prev is False and cur is True:
            label = RegressionLabel.IMPROVED
        elif prev is True and cur is True:
            label = RegressionLabel.UNCHANGED_PASS
        elif prev is False and cur is False:
            label = RegressionLabel.UNCHANGED_FAIL
        else:
            label = RegressionLabel.NEW_CASE
        deltas.append(
            CaseDelta(
                case_id=cid,
                label=label,
                baseline_passed=prev,
                current_passed=cur,
            )
        )
    return deltas

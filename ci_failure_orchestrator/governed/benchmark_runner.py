"""Synthetic benchmark runner for the governed pipeline (labeled synthetic)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pipeline import GovernedAgentPipeline, failure_event_from_dict
from .retry import RetryBudget
from .store import SQLiteGovernedStore


def run_benchmark_suite(cases_dir: str | Path) -> dict[str, Any]:
    root = Path(cases_dir)
    files = sorted(root.glob("*.json"))
    passed = 0
    failed = 0
    results: list[dict[str, Any]] = []

    for path in files:
        case = json.loads(path.read_text(encoding="utf-8"))
        event = failure_event_from_dict(case["failure"])
        store = SQLiteGovernedStore(path=path.with_suffix(".db"))
        pipeline = GovernedAgentPipeline(
            store=store,
            retry_budget=RetryBudget(max_attempts=int(case.get("max_attempts", 3))),
        )
        outcome = pipeline.run(event)
        expected_states = set(case.get("expected_states") or [])
        expected_class = case.get("expected_class")
        forbid_success = bool(case.get("forbid_success", False))

        ok = True
        reasons: list[str] = []
        if expected_class and outcome.classification:
            if outcome.classification.failure_class != expected_class:
                ok = False
                reasons.append(
                    f"class={outcome.classification.failure_class}!=expected={expected_class}"
                )
        if expected_states and outcome.state.value not in expected_states:
            ok = False
            reasons.append(f"state={outcome.state.value} not in {sorted(expected_states)}")
        if forbid_success and outcome.state.value == "SUCCEEDED":
            ok = False
            reasons.append("success_forbidden_for_case")

        if ok:
            passed += 1
        else:
            failed += 1
        results.append(
            {
                "case": path.name,
                "synthetic": True,
                "ok": ok,
                "state": outcome.state.value,
                "class": getattr(outcome.classification, "failure_class", None),
                "reasons": reasons,
            }
        )
        # cleanup per-case db
        try:
            path.with_suffix(".db").unlink(missing_ok=True)
        except OSError:
            pass

    return {
        "suite": "governed-synthetic",
        "synthetic": True,
        "total": len(files),
        "passed": passed,
        "failed": failed,
        "results": results,
    }

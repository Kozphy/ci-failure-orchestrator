#!/usr/bin/env python3
"""Offline demo of the LangGraph diagnosis flow (no API keys, no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ci_failure_orchestrator.diagnosis_graph import DiagnosisGraphRunner, MockHypothesisProvider
from ci_failure_orchestrator.foundation.models import FailureEvent
from ci_failure_orchestrator.foundation.persistence import RunPersistence


def main() -> int:
    """Run one confirmed diagnosis and print a machine-readable summary."""
    out = ROOT / "artifacts" / "diagnosis-demo"
    persistence = RunPersistence(out)
    runner = DiagnosisGraphRunner(
        out,
        persistence=persistence,
        provider=MockHypothesisProvider(category="test_failure"),
    )
    event = FailureEvent.from_dict(
        {
            "workflow": "ci",
            "job": "test",
            "failed_step": "pytest",
            "message": "AssertionError: expected True got False",
            "log_excerpt": "FAILED tests/test_app.py::test_login - AssertionError",
        },
        run_id="demo-diag-1",
    )
    result = runner.run(event)
    summary = {
        "workflow_status": result.workflow_status,
        "status": result.status.value,
        "technical_status": result.technical_status,
        "action_ledger": list(runner.action_ledger),
        "evidence": str(out / "runs" / "demo-diag-1" / "diagnosis" / "decision.json"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if result.workflow_status == "DIAGNOSIS_CONFIRMED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

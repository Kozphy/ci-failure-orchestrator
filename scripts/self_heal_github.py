from __future__ import annotations

import argparse
import json
from pathlib import Path

from ci_failure_orchestrator.classifier import classify_error

TRANSIENT_TYPES = {"FLAKY_TEST", "NETWORK_ERROR"}


def decide(log_text: str) -> dict[str, object]:
    error_type, confidence = classify_error(log_text)
    action = "RERUN_FAILED" if error_type in TRANSIENT_TYPES and confidence >= 0.8 else "ESCALATE_REPAIR"
    return {
        "error_type": error_type,
        "confidence": confidence,
        "action": action,
        "reason": (
            "transient failure class is eligible for one bounded failed-job rerun"
            if action == "RERUN_FAILED"
            else "failure is not safe to auto-rerun; hand off to repair/evaluation path"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded GitHub Actions self-heal decision")
    parser.add_argument("--logs", required=True, help="Path containing failed-job logs")
    parser.add_argument("--output", default="self-heal-decision.json")
    args = parser.parse_args()

    log_text = Path(args.logs).read_text(encoding="utf-8", errors="replace")
    result = decide(log_text)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

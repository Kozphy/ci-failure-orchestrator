from __future__ import annotations

import argparse
import json
from pathlib import Path

from ci_failure_orchestrator.deployment_evidence import EvidenceValidationError, verify_evidence_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify measured production deployment evidence and emit a tamper-evident proof bundle"
    )
    parser.add_argument("evidence", type=Path, help="Measured production evidence JSON")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/deployment-evidence.json"),
        help="Output proof report",
    )
    args = parser.parse_args()

    try:
        report = verify_evidence_file(args.evidence)
    except (EvidenceValidationError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"decision": "BLOCK", "error": str(exc)}, indent=2))
        return 2

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

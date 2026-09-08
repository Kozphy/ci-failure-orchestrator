from __future__ import annotations

import argparse
import json
from pathlib import Path

from ci_failure_orchestrator.production_proof import (
    ProductionPolicy,
    evaluate_production_gate,
    metrics_from_mapping,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate production-proof release thresholds")
    parser.add_argument("metrics", type=Path, help="JSON file containing measured production metrics")
    parser.add_argument("--report", type=Path, default=Path("artifacts/production-gate.json"))
    args = parser.parse_args()

    data = json.loads(args.metrics.read_text(encoding="utf-8"))
    metrics = metrics_from_mapping(data)
    result = evaluate_production_gate(metrics, ProductionPolicy())
    report = {"metrics": metrics.to_dict(), "gate": result.to_dict()}

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

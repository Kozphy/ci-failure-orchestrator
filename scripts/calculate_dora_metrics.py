from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from ci_failure_orchestrator.dora_metrics import DeploymentEvent, calculate_dora_metrics


def parse_event(item: dict[str, object]) -> DeploymentEvent:
    return DeploymentEvent(
        deployment_id=str(item["deployment_id"]),
        commit_sha=str(item["commit_sha"]),
        started_at=datetime.fromisoformat(str(item["started_at"]).replace("Z", "+00:00")),
        completed_at=datetime.fromisoformat(str(item["completed_at"]).replace("Z", "+00:00")),
        succeeded=bool(item["succeeded"]),
        rollback_performed=bool(item.get("rollback_performed", False)),
        recovered_at=(
            datetime.fromisoformat(str(item["recovered_at"]).replace("Z", "+00:00"))
            if item.get("recovered_at")
            else None
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate DORA-style deployment metrics from deployment evidence")
    parser.add_argument("events", type=Path, help="JSON file containing a list of deployment events")
    parser.add_argument("--report", type=Path, default=Path("artifacts/dora-metrics.json"))
    args = parser.parse_args()

    raw = json.loads(args.events.read_text(encoding="utf-8"))
    events = [parse_event(item) for item in raw]
    metrics = calculate_dora_metrics(events)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(metrics.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(metrics.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

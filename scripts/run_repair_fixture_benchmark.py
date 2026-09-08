from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from ci_failure_orchestrator.repair import RepairPlanner, SandboxRepairExecutor, pytest_verifier
from ci_failure_orchestrator.repair_loop import run_repair_case, summarize_repair_runs


def materialize_fixture(root: Path, case: dict) -> Path:
    fixture = root / case["id"]
    fixture.mkdir(parents=True, exist_ok=True)
    for relative, content in case.get("initial_files", {}).items():
        path = fixture / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser(description="Run executable repair fixtures in disposable sandboxes")
    parser.add_argument("corpus", nargs="?", default="benchmark/repair_fixture_corpus.v1.json")
    parser.add_argument("--output", default="artifacts/repair-fixture-benchmark.json")
    parser.add_argument("--retry-budget", type=int, default=2)
    args = parser.parse_args()

    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    planner = RepairPlanner()
    executor = SandboxRepairExecutor(pytest_verifier())
    runs = []

    with tempfile.TemporaryDirectory(prefix="ci-repair-fixtures-") as tmp:
        root = Path(tmp)
        for case in corpus.get("cases", []):
            fixture = materialize_fixture(root, case)
            runs.append(run_repair_case(fixture, case, planner, executor, retry_budget=args.retry_budget))

    metrics = summarize_repair_runs(runs)
    payload = {
        "benchmark": "repair-fixture-corpus",
        "version": corpus.get("version", "unknown"),
        "evidence_type": "executable_reproducible_repair_benchmark",
        "claim_scope": "deterministic allowlisted file repairs in disposable sandboxes",
        "metrics": metrics.to_dict(),
        "runs": [run.to_dict() for run in runs],
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

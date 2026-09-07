from __future__ import annotations

import json
from pathlib import Path

from ci_failure_orchestrator.ablation import evaluate_repair_ablations
from ci_failure_orchestrator.repair import SandboxRepairExecutor, pytest_verifier


def main() -> int:
    corpus = json.loads(Path("benchmark/repair_fixtures.v1.json").read_text(encoding="utf-8"))
    cases = corpus["cases"]
    fixture_root = Path("benchmark/fixtures")

    def executor_factory(case: dict) -> SandboxRepairExecutor:
        return SandboxRepairExecutor(pytest_verifier())

    results = evaluate_repair_ablations(cases, fixture_root, executor_factory)
    payload = {
        "benchmark": "repair-ablation",
        "version": corpus.get("version", "unknown"),
        "evidence_type": "executable_reproducible_ablation",
        "claim_scope": "deterministic repair fixtures only",
        "systems": [result.to_dict() for result in results],
    }
    output = Path("artifacts/repair-ablation.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

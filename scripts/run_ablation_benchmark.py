from __future__ import annotations

import json
from pathlib import Path
import tempfile

from ci_failure_orchestrator.ablation import evaluate_repair_ablations
from ci_failure_orchestrator.repair import SandboxRepairExecutor, pytest_verifier


def materialize_case(root: Path, case: dict) -> dict:
    fixture_name = case["id"]
    fixture = root / fixture_name
    fixture.mkdir(parents=True, exist_ok=True)
    for relative, content in case.get("initial_files", {}).items():
        path = fixture / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    materialized = dict(case)
    materialized["fixture"] = fixture_name
    return materialized


def main() -> int:
    corpus = json.loads(Path("benchmark/repair_fixture_corpus.v1.json").read_text(encoding="utf-8"))

    def executor_factory(case: dict) -> SandboxRepairExecutor:
        return SandboxRepairExecutor(pytest_verifier())

    with tempfile.TemporaryDirectory(prefix="ci-ablation-fixtures-") as tmp:
        fixture_root = Path(tmp)
        cases = [materialize_case(fixture_root, case) for case in corpus["cases"]]
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

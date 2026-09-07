from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from ci_failure_orchestrator.agent_eval import ReplayAgentBackend, run_agent_case, summarize_agent_results
from ci_failure_orchestrator.repair import SandboxRepairExecutor, pytest_verifier
from scripts.run_repair_fixture_benchmark import materialize_fixture


def main() -> int:
    parser = argparse.ArgumentParser(description="Run provider-neutral agent repair evaluation")
    parser.add_argument("corpus", nargs="?", default="benchmark/repair_fixture_corpus.v1.json")
    parser.add_argument("--output", default="artifacts/agent-eval-benchmark.json")
    parser.add_argument("--retry-budget", type=int, default=2)
    args = parser.parse_args()

    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    backend = ReplayAgentBackend()
    executor = SandboxRepairExecutor(pytest_verifier())
    results = []

    with tempfile.TemporaryDirectory(prefix="ci-agent-fixtures-") as tmp:
        root = Path(tmp)
        for case in corpus.get("cases", []):
            fixture = materialize_fixture(root, case)
            results.append(run_agent_case(fixture, case, backend, executor, retry_budget=args.retry_budget))

    metrics = summarize_agent_results(results)
    payload = {
        "benchmark": "agent-repair-evaluation",
        "version": corpus.get("version", "unknown"),
        "evidence_type": "replay_agent_executable_benchmark",
        "claim_scope": "provider-neutral agent interface, sandbox verification, token/cost telemetry contract",
        "limitations": [
            "Replay backend makes no external model call.",
            "Token counts are estimated from text length, not provider-reported usage.",
            "Zero cost is a replay property and must not be presented as real model cost.",
        ],
        "metrics": metrics.to_dict(),
        "results": [result.to_dict() for result in results],
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

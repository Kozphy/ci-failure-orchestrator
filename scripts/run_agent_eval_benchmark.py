from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from ci_failure_orchestrator.agent_eval import ReplayAgentBackend, run_agent_case, summarize_agent_results
from ci_failure_orchestrator.repair import SandboxRepairExecutor, pytest_verifier


def materialize_fixture(root: Path, case: dict) -> Path:
    fixture = root / case["id"]
    fixture.mkdir(parents=True, exist_ok=True)
    for relative, content in case.get("initial_files", {}).items():
        path = fixture / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser(description="Run provider-neutral agent repair evaluation")
    parser.add_argument("corpus", nargs="?", default="benchmark/repair_fixture_corpus.v1.json")
    parser.add_argument("--output", default="artifacts/agent-eval-benchmark.json")
    parser.add_argument("--retry-budget", type=int, default=2)
    parser.add_argument("--backend", choices=("replay", "openai"), default="replay")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    if args.backend == "openai":
        from ci_failure_orchestrator.openai_backend import OpenAIAgentBackend
        backend = OpenAIAgentBackend(model=args.model)
        evidence_type = "live_provider_agent_executable_benchmark"
        limitations = [
            "Provider-reported token usage and wall-clock latency are measured.",
            "Dollar cost is intentionally not inferred from hard-coded prices; join with provider billing/export data before claiming actual cost.",
            "Results apply only to the versioned fixture corpus, model, prompt, and retry policy recorded by this run.",
        ]
    else:
        backend = ReplayAgentBackend()
        evidence_type = "replay_agent_executable_benchmark"
        limitations = [
            "Replay backend makes no external model call.",
            "Token counts are estimated from text length, not provider-reported usage.",
            "Zero cost is a replay property and must not be presented as real model cost.",
        ]

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
        "backend": args.backend,
        "evidence_type": evidence_type,
        "claim_scope": "agent proposals, sandbox verification, retry policy, and provider telemetry",
        "limitations": limitations,
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

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ci_failure_orchestrator.live_semantic_merge_eval import (
    run_live_semantic_case,
    summarize_live_semantic_runs,
)
from ci_failure_orchestrator.openai_merge_resolver import OpenAISemanticMergeProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live semantic merge-conflict evaluation")
    parser.add_argument("--corpus", default="benchmark/live_semantic_merge_corpus.v1.json")
    parser.add_argument("--output", default="artifacts/live-semantic-merge-eval.json")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--model", default="gpt-5.6")
    parser.add_argument("--min-confidence", type=float, default=0.80)
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for live semantic merge evaluation")

    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    provider = OpenAISemanticMergeProvider(model=args.model)
    runs = []
    for trial in range(1, args.trials + 1):
        for case in corpus.get("cases", []):
            runs.append(
                run_live_semantic_case(
                    case,
                    provider,
                    trial=trial,
                    min_confidence=args.min_confidence,
                )
            )

    metrics = summarize_live_semantic_runs(runs)
    payload = {
        "benchmark": "live-semantic-merge-evaluation",
        "version": corpus.get("version", "unknown"),
        "evidence_type": "live_model_held_out_synthetic_conflict_benchmark",
        "model": args.model,
        "trials_per_case": args.trials,
        "claim_scope": "live provider telemetry on held-out synthetic semantic merge conflicts; not production incident data",
        "metrics": metrics.to_dict(),
        "results": [run.to_dict() for run in runs],
        "limitations": [
            "The corpus is synthetic and small.",
            "Fragment checks are deterministic proxies for semantic verification.",
            "Dollar cost is not inferred from hard-coded model pricing; combine token evidence with provider billing data.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

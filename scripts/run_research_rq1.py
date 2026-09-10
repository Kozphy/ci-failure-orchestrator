from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from ci_failure_orchestrator.research_evaluation import (
    canonical_json_digest,
    evaluate_case_outcomes,
    summarize_paired_outcomes,
)


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run RQ1 paired evaluation: dependency-aware ranking vs latest-visible baseline"
    )
    parser.add_argument("--corpus", default="benchmark/ci_failure_corpus.v1.json")
    parser.add_argument("--output", default="artifacts/research/rq1.json")
    parser.add_argument("--bootstrap-trials", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260910)
    args = parser.parse_args()

    corpus_path = Path(args.corpus)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    outcomes = evaluate_case_outcomes(corpus)
    metrics = summarize_paired_outcomes(
        outcomes, bootstrap_trials=args.bootstrap_trials, seed=args.seed
    )

    payload = {
        "research_question": "RQ1",
        "claim": "dependency-aware ranking improves root-cause identification over a latest-visible failure baseline",
        "evidence_type": "paired_reproducible_synthetic_benchmark",
        "claim_scope": "synthetic CI cascade corpus only; not production incidents",
        "benchmark": {
            "path": str(corpus_path),
            "version": corpus.get("version", "unknown"),
            "sha256": canonical_json_digest(corpus),
        },
        "method": "dependency_aware_root_cause_ranker",
        "baseline": "latest_visible_failure",
        "statistics": {
            "bootstrap_trials": args.bootstrap_trials,
            "seed": args.seed,
            "paired_test": "two-sided exact McNemar/binomial test",
        },
        "metrics": metrics.to_dict(),
        "case_outcomes": [outcome.to_dict() for outcome in outcomes],
        "provenance": {
            "repo_commit_sha": git_sha(),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    }
    payload["result_sha256"] = canonical_json_digest(payload)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

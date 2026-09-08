from __future__ import annotations

import argparse
import json
from pathlib import Path

from ci_failure_orchestrator.corpus_benchmark import evaluate_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the reproducible CI failure corpus benchmark")
    parser.add_argument("corpus", nargs="?", default="benchmark/ci_failure_corpus.v1.json")
    parser.add_argument("--output", default="artifacts/corpus-benchmark.json")
    args = parser.parse_args()

    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    metrics = evaluate_corpus(corpus)
    payload = {
        "benchmark": "ci-failure-corpus",
        "version": corpus.get("version", "unknown"),
        "evidence_type": "synthetic_reproducible_benchmark",
        "claim_scope": "root-cause ranking and cascade elimination only",
        "metrics": metrics.to_dict(),
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

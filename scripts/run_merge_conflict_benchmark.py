from __future__ import annotations

import json
from pathlib import Path

from ci_failure_orchestrator.merge_conflict_benchmark import (
    evaluate_merge_conflict_case,
    summarize_merge_conflict_results,
)


def main() -> int:
    corpus_path = Path("benchmark/merge_conflict_corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    results = [evaluate_merge_conflict_case(case) for case in corpus.get("cases", [])]
    metrics = summarize_merge_conflict_results(results)
    payload = {
        "benchmark": "merge-conflict-resolution",
        "version": corpus.get("version", "unknown"),
        "evidence_type": "held_out_synthetic_conflict_benchmark",
        "claim_scope": "deterministic resolver only; semantic cases must fail closed without a live provider",
        "metrics": metrics.to_dict(),
        "results": [result.to_dict() for result in results],
    }
    output = Path("artifacts/merge-conflict-benchmark.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ci_failure_orchestrator.baselines import run_baseline


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accuracy(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return round(sum(bool(row["correct"]) for row in rows) / len(rows), 4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic research baseline matrix")
    parser.add_argument("--corpus", default="benchmark/ci_failure_corpus.v1.json")
    parser.add_argument("--baselines", nargs="+", default=["B0", "B3"])
    parser.add_argument("--output", default="artifacts/research/baseline-matrix.json")
    args = parser.parse_args()

    corpus_path = Path(args.corpus)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    systems = []
    for baseline_id in args.baselines:
        predictions = [item.to_dict() for item in run_baseline(baseline_id, corpus)]
        systems.append(
            {
                "baseline_id": baseline_id,
                "cases": len(predictions),
                "top1_accuracy": accuracy(predictions),
                "predictions": predictions,
            }
        )

    payload = {
        "benchmark": "ci-failure-corpus",
        "benchmark_version": corpus.get("version", "unknown"),
        "benchmark_sha256": file_sha256(corpus_path),
        "evidence_type": "executable_deterministic_research_baseline",
        "claim_scope": "RQ1 root-cause identification on the supplied corpus only",
        "systems": systems,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["result_sha256"] = hashlib.sha256(canonical).hexdigest()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

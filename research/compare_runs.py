"""Check that two raw experiment directories agree on everything except timing and identity fields.

    python -m research.compare_runs research/results/raw/<run-a> research/results/raw/<run-b>

Exit code 0 when predictions, repair decisions, candidate facts and metrics match after removing
volatile fields (latencies, timestamps, experiment IDs, git state); 1 otherwise, with the differing paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

VOLATILE_KEYS = frozenset({
    "latency_ms", "experiment_id", "timestamp", "git_commit", "git_dirty", "command", "config_path",
    "candidate_latency_ms_p50", "candidate_latency_ms_p95", "case_latency_ms_p50", "case_latency_ms_p95",
    "latency_ms_p50", "latency_ms_p95", "environment",
})
COMPARED = ("predictions.jsonl", "repairs.jsonl", "evidence.jsonl", "metrics.json", "errors.jsonl")


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [_strip(json.loads(line)) for line in text.splitlines() if line.strip()]
    return _strip(json.loads(text))


def _diff(a: Any, b: Any, path: str, out: list[str], limit: int = 20) -> None:
    if len(out) >= limit:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            _diff(a.get(key, "<missing>"), b.get(key, "<missing>"), f"{path}.{key}", out, limit)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for idx, (x, y) in enumerate(zip(a, b, strict=True)):
            _diff(x, y, f"{path}[{idx}]", out, limit)
    elif a != b:
        out.append(f"{path}: {str(a)[:80]!r} != {str(b)[:80]!r}")


def compare(run_a: Path, run_b: Path) -> list[str]:
    """Return differences between two raw runs (empty when they agree)."""
    out: list[str] = []
    for name in COMPARED:
        _diff(_load(run_a / name), _load(run_b / name), name, out)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_a", type=Path)
    parser.add_argument("run_b", type=Path)
    args = parser.parse_args(argv)
    diffs = compare(args.run_a, args.run_b)
    print(json.dumps({"identical_after_removing_volatile_fields": not diffs, "differences": diffs}, indent=2))
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main())

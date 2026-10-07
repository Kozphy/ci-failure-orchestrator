"""Annotation QA for repair fixtures: ``python -m research.fixture_qa [--case ID ...]``.

Checks, for every repair case, that the visible CI command and the hidden oracle both fail at the base
commit, that every candidate materializes, and that candidate labels agree with the oracle (a
``correct`` candidate is green and passes the oracle; a ``semantically_wrong`` or ``regression``
candidate does not pass both). Exit code 1 if any issue is found. This is fixture QA, not an
evaluation: it reports no system metrics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .dataset import load_dataset
from .paths import DATASETS_DIR, SPLITS
from .repair import run_case


def main(argv: list[str] | None = None) -> int:
    """Run fixture QA and print one JSON line per case."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--datasets", type=Path, default=DATASETS_DIR)
    parser.add_argument("--split", action="append", choices=SPLITS, help="splits to check (default: all)")
    parser.add_argument("--case", action="append", help="limit to these case ids")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)

    dataset = load_dataset(args.datasets)
    cases = [
        c for c in dataset.cases(args.split or SPLITS)
        if "repair" in c.get("tracks", []) and (not args.case or c["case_id"] in args.case)
    ]
    failed = 0
    for case in cases:
        run = run_case(case, seed=0, budget=1, timeout=args.timeout, systems=())
        issues = list(run.base_checks["issues"])
        for fact in run.facts:
            if fact.error:
                issues.append(f"{fact.candidate_id}:error:{fact.error}")
            issues.extend(f"{fact.candidate_id}:{issue}" for issue in fact.annotation_issues)
        failed += bool(issues)
        print(json.dumps({
            "case_id": case["case_id"],
            "ok": not issues,
            "issues": issues,
            "candidates": {
                f.candidate_id: {
                    "label": f.label, "green": f.ci_green, "policy": f.policy_outcome,
                    "state": f.remediation_state, "verified": f.locally_verified,
                    "verified_no_policy": f.verified_without_policy, "oracle": f.oracle_passed,
                    "forbidden": f.forbidden_diff_codes,
                }
                for f in run.facts
            },
            "latency_ms": run.latency_ms,
        }, sort_keys=True))
    print(json.dumps({"cases": len(cases), "cases_with_issues": failed}), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

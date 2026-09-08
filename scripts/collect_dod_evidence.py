#!/usr/bin/env python3
"""Collect independent Definition of Done evidence fragments into one bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ci_failure_orchestrator.evidence_collector import collect_evidence


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for evidence collection."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fragment",
        action="append",
        required=True,
        help="Path to an independently produced JSON evidence fragment; repeatable",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path for the merged evidence JSON",
    )
    parser.add_argument(
        "--report",
        help="Optional path for a collection report containing conflict details",
    )
    return parser


def main() -> int:
    """Merge fragments, reject conflicts, and write deterministic JSON output."""

    args = build_parser().parse_args()
    fragments = [
        json.loads(Path(path).read_text(encoding="utf-8"))
        for path in args.fragment
    ]
    result = collect_evidence(fragments)

    if args.report:
        Path(args.report).write_text(
            json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if not result.valid:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 2

    Path(args.output).write_text(
        json.dumps(result.evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"valid": True, "output": args.output}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

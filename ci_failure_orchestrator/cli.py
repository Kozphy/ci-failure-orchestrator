from __future__ import annotations

import argparse
import json

from .audit import HashChainedAuditLog
from .classifier import classify_error
from .config import load_failures, load_pipeline
from .graph import PipelineGraph
from .ranker import RootCauseRanker


def cmd_classify(args: argparse.Namespace) -> int:
    error_type, confidence = classify_error(args.message)
    print(json.dumps({"error_type": error_type, "confidence": confidence}, indent=2))
    return 0


def cmd_rank(args: argparse.Namespace) -> int:
    stages = load_pipeline(args.pipeline)
    failures = load_failures(args.failures)
    graph = PipelineGraph(stages)
    ranked = RootCauseRanker(graph).rank(failures)
    output = [item.to_dict() for item in ranked]
    print(json.dumps(output, indent=2))
    if args.audit:
        log = HashChainedAuditLog(args.audit)
        log.append("root_cause_ranked", {"ranking": output})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ci-orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    classify = sub.add_parser("classify", help="Classify a CI error message")
    classify.add_argument("message")
    classify.set_defaults(func=cmd_classify)

    rank = sub.add_parser("rank", help="Rank failures by probable root cause")
    rank.add_argument("--pipeline", required=True)
    rank.add_argument("--failures", required=True)
    rank.add_argument("--audit")
    rank.set_defaults(func=cmd_rank)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

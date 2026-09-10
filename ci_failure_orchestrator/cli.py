"""Command-line interface for CI failure orchestrator.

This module provides the CLI entry point for CI failure analysis, including
error classification, root-cause ranking, and GitHub Actions job analysis
with optional audit logging.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
from .audit import HashChainedAuditLog
from .classifier import classify_error
from .config import load_failures, load_pipeline
from .graph import PipelineGraph
from .ranker import RootCauseRanker
from .causal import infer_causal_edges
from .verification import plan_verification
from .github_ingest import stages_from_jobs, failures_from_jobs


def _dump(value):
    """Print a value as formatted JSON to stdout.

    Args:
        value: Value to serialize as JSON.
    """
    print(json.dumps(value, indent=2))


def cmd_classify(args):
    """Classify a CI error message into error type and confidence.

    Args:
        args: Parsed command-line arguments with message attribute.

    Returns:
        Exit code 0 on success.

    Output:
        JSON object with error_type and confidence fields.
    """
    error_type, confidence = classify_error(args.message)
    _dump({"error_type": error_type, "confidence": confidence})
    return 0


def cmd_rank(args):
    """Rank failures by probable root cause using pipeline graph analysis.

    Args:
        args: Parsed command-line arguments with pipeline, failures, and optional audit path.

    Returns:
        Exit code 0 on success.

    Output:
        JSON array of ranked failures with root-cause scores and reasoning.

    Side Effects:
        - Appends ranking results to audit log if --audit is provided.
    """
    graph = PipelineGraph(load_pipeline(args.pipeline))
    ranked = RootCauseRanker(graph).rank(load_failures(args.failures))
    output = [item.to_dict() for item in ranked]
    _dump(output)
    if args.audit:
        HashChainedAuditLog(args.audit).append("root_cause_ranked", {"ranking": output})
    return 0


def cmd_analyze(args):
    """Analyze normalized GitHub Actions jobs and logs for root-cause analysis.

    This command processes GitHub Actions job data, extracts stages and failures,
    builds a pipeline graph, ranks root causes, infers causal edges, and generates
    a verification plan.

    Args:
        args: Parsed command-line arguments with jobs, optional logs, and optional audit path.

    Returns:
        Exit code 0 on success.

    Output:
        JSON object containing:
        - root_cause: Top-ranked root-cause stage ID.
        - ranking: Array of ranked failures with scores.
        - causal_edges: Array of inferred causal relationships.
        - verification_plan: Array of verification steps.

    Side Effects:
        - Appends analysis results to audit log if --audit is provided.
    """
    raw = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
    jobs = raw.get("jobs", raw) if isinstance(raw, dict) else raw
    logs = json.loads(Path(args.logs).read_text(encoding="utf-8")) if args.logs else {}
    stages = stages_from_jobs(jobs)
    failures = failures_from_jobs(jobs, logs)
    graph = PipelineGraph(stages)
    ranked = RootCauseRanker(graph).rank(failures)
    edges = infer_causal_edges(graph, failures)
    root = ranked[0].failure.stage if ranked else None
    plan = plan_verification(graph, root, {f.stage for f in failures}) if root else []
    result = {"root_cause": root, "ranking": [r.to_dict() for r in ranked], "causal_edges": [e.to_dict() for e in edges], "verification_plan": [s.to_dict() for s in plan]}
    _dump(result)
    if args.audit:
        HashChainedAuditLog(args.audit).append("github_actions_analyzed", result)
    return 0


def build_parser():
    """Build the argument parser for the CI orchestrator CLI.

    Returns:
        Configured ArgumentParser with subcommands for classify, rank, and analyze.
    """
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
    analyze = sub.add_parser("analyze", help="Analyze normalized GitHub Actions jobs and logs")
    analyze.add_argument("--jobs", required=True)
    analyze.add_argument("--logs")
    analyze.add_argument("--audit")
    analyze.set_defaults(func=cmd_analyze)
    return parser


def main():
    """Main entry point for the CI orchestrator CLI.

    Returns:
        Exit code from the executed command (0 on success, non-zero on failure).
    """
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

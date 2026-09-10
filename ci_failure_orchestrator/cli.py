from __future__ import annotations

"""Command-line interface for CI Failure Orchestrator.

This module provides the public CLI entry point (ci-orchestrator) with
subcommands for classifying errors, ranking failures, analyzing GitHub Actions
jobs, and evaluating Definition of Done evidence.

Module responsibility:
    - Parse command-line arguments
    - Dispatch to appropriate handlers
    - Format output as stable, human-readable JSON
    - Support optional hash-chained audit logging

Key invariants:
    - All commands produce JSON output on stdout
    - Exit code 0 means success, 1 means failure (for dod command)
    - Audit logging is optional and append-only

Safety boundaries:
    - No mutations beyond file reads and optional audit writes
    - All file paths are validated before access
    - JSON parsing errors are propagated (fail-fast)

Subcommands:
    - classify: Classify a CI error message
    - rank: Rank normalized failures by probable root cause
    - analyze: Analyze normalized GitHub Actions jobs and logs
    - dod: Derive PRODUCTION_DONE or NOT_DONE from JSON evidence

Audit Notes:
    - Audit logs use HashChainedAuditLog for tamper-evidence
    - Each command records its specific event type and payload
    - Audit path is optional; if not provided, no audit logging occurs
"""

import argparse
import json
from pathlib import Path

from .audit import HashChainedAuditLog
from .classifier import classify_error
from .config import load_failures, load_pipeline
from .definition_of_done import evaluate_definition_of_done
from .graph import PipelineGraph
from .ranker import RootCauseRanker
from .causal import infer_causal_edges
from .verification import plan_verification
from .github_ingest import stages_from_jobs, failures_from_jobs


def _dump(value):
    """Print a stable, human-readable JSON representation.

    Args:
        value: JSON-serializable value to print

    Side effects:
        Prints JSON to stdout with 2-space indentation.
    """
    print(json.dumps(value, indent=2))


def cmd_classify(args):
    """Classify one CI error message.

    Args:
        args: Parsed arguments with message string

    Returns:
        Exit code 0 on success

    Side effects:
        Prints classification result as JSON to stdout.
    """
    error_type, confidence = classify_error(args.message)
    _dump({"error_type": error_type, "confidence": confidence})
    return 0


def cmd_rank(args):
    """Rank normalized failures by probable root cause.

    Args:
        args: Parsed arguments with --pipeline and --failures paths

    Returns:
        Exit code 0 on success

    Side effects:
        - Reads pipeline and failures JSON files
        - Prints ranking result as JSON to stdout
        - Optionally appends to audit log
    """
    graph = PipelineGraph(load_pipeline(args.pipeline))
    ranked = RootCauseRanker(graph).rank(load_failures(args.failures))
    output = [item.to_dict() for item in ranked]
    _dump(output)
    if args.audit:
        HashChainedAuditLog(args.audit).append("root_cause_ranked", {"ranking": output})
    return 0


def cmd_analyze(args):
    """Analyze normalized GitHub Actions evidence and produce a repair plan.

    Performs end-to-end analysis including:
    - Stage extraction from jobs
    - Failure extraction from jobs and logs
    - Pipeline graph construction
    - Root cause ranking
    - Causal edge inference
    - Verification planning

    Args:
        args: Parsed arguments with --jobs and optional --logs paths

    Returns:
        Exit code 0 on success

    Side effects:
        - Reads jobs and logs JSON files
        - Prints analysis result as JSON to stdout
        - Optionally appends to audit log
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
    result = {
        "root_cause": root,
        "ranking": [r.to_dict() for r in ranked],
        "causal_edges": [e.to_dict() for e in edges],
        "verification_plan": [s.to_dict() for s in plan],
    }
    _dump(result)
    if args.audit:
        HashChainedAuditLog(args.audit).append("github_actions_analyzed", result)
    return 0


def cmd_dod(args):
    """Evaluate production completion from machine-readable evidence.

    Exit code 0 means every required gate is satisfied. Exit code 1 means the
    change is NOT_DONE; missing and failed gates are printed as JSON so CI and
    repair agents can act on concrete evidence instead of an agent assertion.

    Args:
        args: Parsed arguments with --evidence path

    Returns:
        Exit code 0 if PRODUCTION_DONE, 1 if NOT_DONE

    Side effects:
        - Reads evidence JSON file
        - Prints evaluation result as JSON to stdout
        - Optionally appends to audit log
    """
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    result = evaluate_definition_of_done(evidence)
    payload = result.to_dict()
    _dump(payload)
    if args.audit:
        HashChainedAuditLog(args.audit).append("definition_of_done_evaluated", payload)
    return 0 if result.done else 1


def build_parser():
    """Build the public command-line interface parser.

    Returns:
        Configured ArgumentParser with all subcommands

    Side effects:
        None.
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

    dod = sub.add_parser(
        "dod",
        help="Derive PRODUCTION_DONE or NOT_DONE from JSON evidence",
    )
    dod.add_argument("--evidence", required=True, help="Path to Definition of Done evidence JSON")
    dod.add_argument("--audit", help="Optional hash-chained audit log path")
    dod.set_defaults(func=cmd_dod)

    return parser


def main():
    """Run the selected CI Failure Orchestrator command.

    Entry point for the ci-orchestrator CLI.

    Returns:
        Exit code from the executed command

    Side effects:
        - Parses command-line arguments
        - Dispatches to the appropriate command handler
    """
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

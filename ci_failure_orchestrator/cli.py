from __future__ import annotations
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
    """Print a stable, human-readable JSON representation."""

    print(json.dumps(value, indent=2))


def cmd_classify(args):
    """Classify one CI error message."""

    error_type, confidence = classify_error(args.message)
    _dump({"error_type": error_type, "confidence": confidence})
    return 0


def cmd_rank(args):
    """Rank normalized failures by probable root cause."""

    graph = PipelineGraph(load_pipeline(args.pipeline))
    ranked = RootCauseRanker(graph).rank(load_failures(args.failures))
    output = [item.to_dict() for item in ranked]
    _dump(output)
    if args.audit:
        HashChainedAuditLog(args.audit).append("root_cause_ranked", {"ranking": output})
    return 0


def cmd_analyze(args):
    """Analyze normalized GitHub Actions evidence and produce a repair plan."""

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
    """

    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    result = evaluate_definition_of_done(evidence)
    payload = result.to_dict()
    _dump(payload)
    if args.audit:
        HashChainedAuditLog(args.audit).append("definition_of_done_evaluated", payload)
    return 0 if result.done else 1


def build_parser():
    """Build the public command-line interface."""

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
    """Run the selected CI Failure Orchestrator command."""

    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

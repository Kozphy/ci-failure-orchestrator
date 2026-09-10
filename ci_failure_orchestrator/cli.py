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
from .github_client import GitHubActionsClient


def _dump(value):
    print(json.dumps(value, indent=2))


def _analyze_jobs(jobs, logs, audit=None, event="github_actions_analyzed"):
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
    if audit:
        HashChainedAuditLog(audit).append(event, result)
    return 0


def cmd_classify(args):
    error_type, confidence = classify_error(args.message)
    _dump({"error_type": error_type, "confidence": confidence})
    return 0


def cmd_rank(args):
    graph = PipelineGraph(load_pipeline(args.pipeline))
    ranked = RootCauseRanker(graph).rank(load_failures(args.failures))
    output = [item.to_dict() for item in ranked]
    _dump(output)
    if args.audit:
        HashChainedAuditLog(args.audit).append("root_cause_ranked", {"ranking": output})
    return 0


def cmd_analyze(args):
    raw = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
    jobs = raw.get("jobs", raw) if isinstance(raw, dict) else raw
    logs = json.loads(Path(args.logs).read_text(encoding="utf-8")) if args.logs else {}
    return _analyze_jobs(jobs, logs, args.audit)


def cmd_analyze_run(args):
    client = GitHubActionsClient(token=args.token, api_url=args.api_url, timeout=args.timeout)
    evidence = client.collect_run(args.repo, args.run_id, include_logs=not args.no_logs)
    return _analyze_jobs(evidence.jobs, evidence.logs, args.audit, event="github_workflow_run_analyzed")


def build_parser():
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

    analyze_run = sub.add_parser("analyze-run", help="Fetch and analyze a GitHub Actions workflow run")
    analyze_run.add_argument("--repo", required=True, help="Repository in owner/name format")
    analyze_run.add_argument("--run-id", required=True, type=int, help="GitHub Actions workflow run ID")
    analyze_run.add_argument("--token", help="GitHub token; defaults to GITHUB_TOKEN")
    analyze_run.add_argument("--api-url", default="https://api.github.com", help="GitHub API base URL")
    analyze_run.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")
    analyze_run.add_argument("--no-logs", action="store_true", help="Skip failed-job log downloads")
    analyze_run.add_argument("--audit")
    analyze_run.set_defaults(func=cmd_analyze_run)
    return parser


def main():
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

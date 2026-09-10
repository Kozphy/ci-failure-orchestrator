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
from .repository_analysis import analyze_repository
from .pr_analysis import analyze_pull_request


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


def cmd_analyze_repo(args):
    client = GitHubActionsClient(token=args.token, api_url=args.api_url, timeout=args.timeout)
    evidence = client.collect_repository(args.repo, ref=args.ref)
    result = analyze_repository(evidence)
    _dump(result)
    if args.audit:
        HashChainedAuditLog(args.audit).append("github_repository_analyzed", result)
    return 0 if result["repo_status"] == "REPO_HEALTHY" else 2


def cmd_analyze_pr(args):
    client = GitHubActionsClient(token=args.token, api_url=args.api_url, timeout=args.timeout)
    evidence = client.collect_pull_request(args.repo, args.pr)
    result = analyze_pull_request(evidence)
    _dump(result)
    if args.audit:
        HashChainedAuditLog(args.audit).append("github_pull_request_analyzed", result)
    return 0 if result["pr_decision"] == "PR_READY" else 2


def _add_github_connection_args(parser):
    parser.add_argument("--token", help="GitHub token; defaults to GITHUB_TOKEN")
    parser.add_argument("--api-url", default="https://api.github.com", help="GitHub API base URL")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")


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
    _add_github_connection_args(analyze_run)
    analyze_run.add_argument("--no-logs", action="store_true", help="Skip failed-job log downloads")
    analyze_run.add_argument("--audit")
    analyze_run.set_defaults(func=cmd_analyze_run)

    analyze_repo = sub.add_parser("analyze-repo", help="Analyze repository-wide CI, test, build, and governance evidence")
    analyze_repo.add_argument("--repo", required=True, help="Repository in owner/name format")
    analyze_repo.add_argument("--ref", help="Branch or ref to inspect; defaults to repository default branch")
    _add_github_connection_args(analyze_repo)
    analyze_repo.add_argument("--audit")
    analyze_repo.set_defaults(func=cmd_analyze_repo)

    analyze_pr = sub.add_parser("analyze-pr", help="Evaluate pull-request change risk, reviews, and exact-head CI evidence")
    analyze_pr.add_argument("--repo", required=True, help="Repository in owner/name format")
    analyze_pr.add_argument("--pr", required=True, type=int, help="Pull request number")
    _add_github_connection_args(analyze_pr)
    analyze_pr.add_argument("--audit")
    analyze_pr.set_defaults(func=cmd_analyze_pr)
    return parser


def main():
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

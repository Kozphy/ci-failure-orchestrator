from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import yaml

from .audit import HashChainedAuditLog
from .causal import infer_causal_edges
from .classifier import classify_error
from .config import load_failures, load_pipeline
from .github_client import GitHubActionsClient
from .github_ingest import failures_from_jobs, stages_from_jobs
from .graph import PipelineGraph
from .network_discovery import NetworkCapabilityDiscovery
from .provenance import DependencyProvenanceEvaluator
from .ranker import RootCauseRanker
from .trust import ProviderRegistry, TrustContextBuilder
from .trust_gateway import (
    AllowlistedFileExecutor,
    ExecutionEvaluator,
    MockLLMClient,
    ProposalVerifier,
    RepairProposal,
    RetryBudget,
    TrustToolGateway,
)
from .trust_policy import TrustPolicyEngine
from .verification import plan_verification
from .governed import GovernedAgentPipeline, failure_event_from_dict
from .governed.explain import explain_result, explain_stored_run
from .governed.store import SQLiteGovernedStore
from .foundation import AgentExecutionFoundation, FailureEvent as FoundationFailureEvent


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


def cmd_trust_run(args):
    scenario_path = Path(args.scenario).resolve()
    scenario = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    proposals = []
    for payload in scenario["proposals"]:
        payload = dict(payload)
        payload["verification"] = tuple(payload.get("verification", ()))
        proposals.append(RepairProposal(**payload))
    root = Path(__file__).resolve().parent.parent
    gateway = TrustToolGateway(
        llm=MockLLMClient(proposals),
        context_builder=TrustContextBuilder(
            ProviderRegistry.from_file(args.providers or root / "config" / "providers.yaml"),
            NetworkCapabilityDiscovery(timeout=args.network_timeout),
            DependencyProvenanceEvaluator(scenario_path.parent),
        ),
        policy=TrustPolicyEngine.from_file(args.policies or root / "config" / "policies.yaml"),
        executor=AllowlistedFileExecutor(),
        evaluator=ExecutionEvaluator(),
        verifier=ProposalVerifier(),
        audit=HashChainedAuditLog(args.audit),
        source_workspace=scenario.get("workspace", scenario_path.parent),
        retry_budget=RetryBudget(
            max_attempts=int(scenario.get("max_attempts", 3)),
            max_total_cost=float(scenario.get("max_total_cost", 1.0)),
            max_wall_time=float(scenario.get("max_wall_time", 60.0)),
        ),
    )
    result = gateway.run(scenario.get("prompt", "propose a repair"), human_approved=args.approved)
    policy = result.policy_decision or {}
    evidence = policy.get("evidence") or {}
    print(f"[context] provider={proposals[0].provider if proposals else 'unknown'}")
    print(f"[data] classification={proposals[0].data_classification if proposals else 'unknown'}")
    print()
    print("[policy]")
    print(f"decision={policy.get('decision', 'n/a')}")
    print(f"rule={policy.get('rule_id', 'n/a')}")
    if evidence:
        print(f"external_provider={evidence.get('external_provider')}")
        print(f"data_leaves_host={evidence.get('data_leaves_host')}")
    print()
    print("[action]")
    if result.status == "approval_required":
        print("execution blocked pending approval")
    elif result.status == "denied":
        print("execution denied by policy")
    elif result.status == "verified_success":
        print("sandbox execution verified")
    else:
        print(result.status)
    print()
    _dump({
        "status": result.status,
        "correlation_id": result.correlation_id,
        "policy": result.policy_decision,
        "attempts": [asdict(item) for item in result.attempts],
        "state_history": result.state_history,
        "escalation": result.escalation,
        "metrics": gateway.metrics_snapshot(),
    })
    return 0 if result.status == "verified_success" else 2


def cmd_run(args):
    """Run the governed agent pipeline against a JSON failure fixture."""

    raw = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    event = failure_event_from_dict(raw if isinstance(raw, dict) else raw[0])
    store = SQLiteGovernedStore(args.store) if args.store else SQLiteGovernedStore()
    audit = HashChainedAuditLog(args.audit) if args.audit else None
    pipeline = GovernedAgentPipeline(store=store, audit_log=audit)
    result = pipeline.run(event)
    print(explain_result(result))
    _dump(
        {
            "run_id": result.run_id,
            "state": result.state.value,
            "attempts": result.attempts,
            "metrics": result.metrics_snapshot,
        }
    )
    return 0 if result.state.value == "SUCCEEDED" else 2


def cmd_explain(args):
    store = SQLiteGovernedStore(args.store) if args.store else SQLiteGovernedStore()
    print(explain_stored_run(store, args.run_id))
    return 0


def cmd_replay(args):
    store = SQLiteGovernedStore(args.store) if args.store else SQLiteGovernedStore()
    state = store.load_run(args.run_id)
    if state is None:
        print(json.dumps({"error": "run_not_found", "run_id": args.run_id}, indent=2))
        return 2
    events = store.list_events(args.run_id) if hasattr(store, "list_events") else ()
    _dump({"run": state, "events": list(events)})
    return 0


def cmd_benchmark(args):
    from .governed.benchmark_runner import run_benchmark_suite

    summary = run_benchmark_suite(Path(args.cases))
    _dump(summary)
    return 0 if summary.get("failed", 0) == 0 else 2


def cmd_foundation_benchmark(args):
    """Phase 12 — deterministic foundation golden benchmark suite."""

    from ci_failure_orchestrator.foundation.benchmark import BenchmarkRunner

    cases_dir = Path(args.cases)
    baseline = Path(args.baseline) if args.baseline else cases_dir.parent / "baselines" / "current.json"
    artifacts = Path(args.artifacts) if args.artifacts else Path("artifacts") / "benchmarks"
    runner = BenchmarkRunner(
        cases_dir=cases_dir,
        baseline_path=baseline,
        artifacts_root=artifacts,
        benchmark_mode=True,
    )
    required = None
    if getattr(args, "required_only", False):
        required = True
    elif getattr(args, "optional_only", False):
        required = False
    suite = runner.run_suite(
        case_id=args.case,
        category=args.category,
        tag=args.tag,
        required=required,
        compare_baseline=bool(args.compare_baseline or args.update_baseline),
        update_baseline=bool(args.update_baseline),
        preserve_artifacts=True,
    )
    _dump(
        {
            "suite_run_id": suite.suite_run_id,
            "exit_code": suite.exit_code,
            "passed": sum(1 for r in suite.results if r.passed),
            "failed": sum(1 for r in suite.results if not r.passed),
            "harness_errors": suite.harness_errors,
            "report": {k: str(v) for k, v in suite.report_paths.items()},
            "metrics": suite.metrics.get("metrics", {}),
            "comparison": [c.to_dict() for c in suite.comparison],
            "results": [
                {
                    "case_id": r.case_id,
                    "passed": r.passed,
                    "required": r.required,
                    "run_id": r.run_id,
                    "failure_reason": r.failure_reason,
                    "harness_error": r.harness_error,
                }
                for r in suite.results
            ],
        }
    )
    return suite.exit_code


def cmd_foundation_operations_report(args):
    """Phase 13 — rebuild metrics/SLI/SLO from retained durable runs."""

    from ci_failure_orchestrator.foundation.observability import (
        build_snapshot,
        write_operations_report,
    )

    artifacts = Path(args.artifacts)
    out = Path(args.output)
    snapshot = build_snapshot(
        artifacts,
        source=args.source,
        limit=args.limit,
        slo_config=Path(args.slo_config) if args.slo_config else None,
    )
    paths = write_operations_report(snapshot, out)
    _dump(
        {
            "population": snapshot.population,
            "run_count": snapshot.run_count,
            "slis": [s.to_dict() for s in snapshot.slis],
            "slos": [s.to_dict() for s in snapshot.slos],
            "reports": {k: str(v) for k, v in paths.items()},
            "consistency_issues": [c.to_dict() for c in snapshot.consistency_issues],
        }
    )
    return 0


def cmd_foundation_slo_check(args):
    """Exit non-zero when a required provisional SLO is MISSED."""

    from ci_failure_orchestrator.foundation.observability import build_snapshot
    from ci_failure_orchestrator.foundation.observability.slo import SLOStatus

    snapshot = build_snapshot(
        Path(args.artifacts),
        source=args.source,
        limit=args.limit,
        slo_config=Path(args.slo_config) if args.slo_config else Path("config/slo.json"),
    )
    missed = [s for s in snapshot.slos if s.status is SLOStatus.MISSED]
    insuf = [s for s in snapshot.slos if s.status is SLOStatus.INSUFFICIENT_DATA]
    _dump(
        {
            "slos": [s.to_dict() for s in snapshot.slos],
            "missed": [s.slo_id for s in missed],
            "insufficient_data": [s.slo_id for s in insuf],
        }
    )
    if missed:
        return 1
    if args.fail_insufficient and insuf:
        return 3
    return 0


def cmd_foundation_run(args):
    """Foundation pipeline (Phases 2–10); optional durable artifacts."""

    raw = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    payload = raw.get("failure", raw) if isinstance(raw, dict) else raw[0]
    event = FoundationFailureEvent.from_dict(payload)
    artifacts = Path(args.artifacts) if getattr(args, "artifacts", None) else None
    result = AgentExecutionFoundation(artifacts_root=artifacts).run(event)
    evaluation = result.run.evaluation
    _dump(
        {
            "run_id": result.run.run_id,
            "status": result.status.value,
            "technical_status": result.technical_status,
            "policy_outcome": None
            if result.policy_outcome is None
            else result.policy_outcome.value,
            "workflow_status": result.workflow_status,
            "classification": None
            if result.run.classification is None
            else {
                "category": result.run.classification.category,
                "confidence": result.run.classification.confidence,
                "calibrated": result.run.classification.calibrated,
            },
            "evaluation": None
            if evaluation is None
            else {
                "passed": evaluation.passed,
                "patch_applied": evaluation.patch_applied,
                "target_verification_passed": evaluation.target_verification_passed,
                "forbidden_changes_detected": evaluation.forbidden_changes_detected,
                "evidence": list(evaluation.evidence),
            },
        }
    )
    if result.status.value in {"APPROVED", "SUCCEEDED"}:
        return 0
    if result.status.value == "AWAITING_HUMAN":
        return 3
    return 2


def cmd_foundation_inspect(args):
    from ci_failure_orchestrator.foundation import inspect_run

    info = inspect_run(Path(args.artifacts), args.run_id)
    _dump(info.__dict__)
    return 0


def cmd_foundation_events(args):
    from ci_failure_orchestrator.foundation import replay_events

    for line in replay_events(Path(args.artifacts), args.run_id):
        print(line)
    return 0


def cmd_foundation_resume(args):
    from ci_failure_orchestrator.foundation import resume_run

    decision = resume_run(Path(args.artifacts), args.run_id)
    _dump(
        {
            "status": decision.status.value,
            "run_id": decision.run_id,
            "workflow_status": decision.workflow_status,
            "message": decision.message,
            "last_sequence": decision.last_sequence,
        }
    )
    return 0 if decision.status.value != "INCONSISTENT" else 2


def cmd_foundation_verify(args):
    from ci_failure_orchestrator.foundation import verify_run_consistency

    report = verify_run_consistency(artifacts_root=Path(args.artifacts), run_id=args.run_id)
    _dump(
        {
            "valid": report.valid,
            "issues": [{"code": i.code, "message": i.message} for i in report.issues],
        }
    )
    return 0 if report.valid else 2


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

    trust_run = sub.add_parser("trust-run", help="Run a policy-gated tool proposal scenario")
    trust_run.add_argument("--scenario", required=True)
    trust_run.add_argument("--providers")
    trust_run.add_argument("--policies")
    trust_run.add_argument("--audit", default="evidence/audit.jsonl")
    trust_run.add_argument("--network-timeout", type=float, default=3.0)
    trust_run.add_argument("--approved", action="store_true")
    trust_run.set_defaults(func=cmd_trust_run)

    run_cmd = sub.add_parser("run", help="Run governed agent pipeline on a failure fixture")
    run_cmd.add_argument("--fixture", required=True, help="JSON FailureEvent fixture")
    run_cmd.add_argument("--store", help="SQLite governed run store path")
    run_cmd.add_argument("--audit", help="Optional hash-chained audit JSONL path")
    run_cmd.set_defaults(func=cmd_run)

    explain = sub.add_parser("explain", help="Explain a stored governed run")
    explain.add_argument("run_id")
    explain.add_argument("--store", help="SQLite governed run store path")
    explain.set_defaults(func=cmd_explain)

    replay = sub.add_parser("replay", help="Replay stored governed run events")
    replay.add_argument("run_id")
    replay.add_argument("--store", help="SQLite governed run store path")
    replay.set_defaults(func=cmd_replay)

    bench = sub.add_parser("benchmark", help="Run governed synthetic benchmark suite")
    bench.add_argument(
        "--cases",
        default="benchmarks/cases",
        help="Directory of synthetic benchmark case JSON files",
    )
    bench.set_defaults(func=cmd_benchmark)

    fb = sub.add_parser(
        "foundation-benchmark",
        help="Phase 12 foundation golden benchmark (deterministic, synthetic)",
    )
    fb.add_argument(
        "--cases",
        default="benchmarks/foundation/cases",
        help="Directory of foundation golden case JSON files",
    )
    fb.add_argument(
        "--baseline",
        default="benchmarks/foundation/baselines/current.json",
        help="Baseline JSON path for regression comparison",
    )
    fb.add_argument(
        "--artifacts",
        default="artifacts/benchmarks",
        help="Output root for benchmark reports",
    )
    fb.add_argument("--case", help="Filter by case_id")
    fb.add_argument("--category", help="Filter by category")
    fb.add_argument("--tag", help="Filter by tag")
    fb.add_argument("--required-only", action="store_true")
    fb.add_argument("--optional-only", action="store_true")
    fb.add_argument(
        "--compare-baseline",
        action="store_true",
        help="Compare results to stored baseline",
    )
    fb.add_argument(
        "--update-baseline",
        action="store_true",
        help="Intentionally rewrite baseline after run (never automatic)",
    )
    fb.set_defaults(func=cmd_foundation_benchmark)

    fops = sub.add_parser(
        "foundation-operations-report",
        help="Phase 13 operational metrics/SLI/SLO report from retained runs",
    )
    fops.add_argument("--artifacts", default="artifacts", help="Foundation artifacts root")
    fops.add_argument(
        "--output",
        default="artifacts/observability",
        help="Output directory for metrics/sli/slo/operations reports",
    )
    fops.add_argument("--source", default="runtime", choices=["runtime", "benchmark"])
    fops.add_argument("--limit", type=int, default=None, help="Last N retained runs")
    fops.add_argument("--slo-config", default="config/slo.json")
    fops.set_defaults(func=cmd_foundation_operations_report)

    fslo = sub.add_parser(
        "foundation-slo-check",
        help="Phase 13 SLO check (EXAMPLE targets; exit 1 if MISSED)",
    )
    fslo.add_argument("--artifacts", default="artifacts")
    fslo.add_argument("--source", default="runtime", choices=["runtime", "benchmark"])
    fslo.add_argument("--limit", type=int, default=None)
    fslo.add_argument("--slo-config", default="config/slo.json")
    fslo.add_argument(
        "--fail-insufficient",
        action="store_true",
        help="Exit 3 when required SLOs have INSUFFICIENT_DATA",
    )
    fslo.set_defaults(func=cmd_foundation_slo_check)

    foundation = sub.add_parser(
        "foundation-run",
        help="Foundation pipeline (Phases 2–10); optional durable artifacts",
    )
    foundation.add_argument("--fixture", required=True, help="JSON failure fixture")
    foundation.add_argument(
        "--artifacts",
        help="Artifacts root for durable state/audit/evidence (enables Phase 10 persistence)",
    )
    foundation.set_defaults(func=cmd_foundation_run)

    fi = sub.add_parser("foundation-inspect", help="Inspect durable foundation run state")
    fi.add_argument("run_id")
    fi.add_argument("--artifacts", default="artifacts")
    fi.set_defaults(func=cmd_foundation_inspect)

    fe = sub.add_parser("foundation-events", help="Replay foundation audit timeline (read-only)")
    fe.add_argument("run_id")
    fe.add_argument("--artifacts", default="artifacts")
    fe.set_defaults(func=cmd_foundation_events)

    fr = sub.add_parser("foundation-resume", help="Assess/resume durable foundation run safely")
    fr.add_argument("run_id")
    fr.add_argument("--artifacts", default="artifacts")
    fr.set_defaults(func=cmd_foundation_resume)

    fv = sub.add_parser("foundation-verify", help="Verify foundation run state/audit consistency")
    fv.add_argument("run_id")
    fv.add_argument("--artifacts", default="artifacts")
    fv.set_defaults(func=cmd_foundation_verify)
    return parser


def main():
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

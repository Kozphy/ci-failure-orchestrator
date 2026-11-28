from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

from .audit import HashChainedAuditLog
from .ci_audit import analyze_export, collect_export, render_report
from .foundation import AgentExecutionFoundation
from .foundation import FailureEvent as FoundationFailureEvent
from .github_client import GitHubActionsClient, GitHubAPIError
from .governed import GovernedAgentPipeline, failure_event_from_dict
from .governed.explain import explain_result, explain_stored_run
from .governed.store import SQLiteGovernedStore
from .service import (
    FixRepoConfig,
    GitHubActionsCIProvider,
    apply_fix,
    compute_operational_metrics,
    compute_remediation_metrics,
    failure_from_fixture,
    failure_from_github,
    failure_from_log_file,
    load_remediation_records,
    load_run_measurements,
    load_verification_config,
    read_verification_config_file,
    render_repair_evidence_markdown,
    run_fix_repo,
    task_summary,
    verify_real_ci,
    write_repair_evidence,
)


def _dump(value):
    print(json.dumps(value, indent=2))


def cmd_governed_run(args):
    """Run the governed pipeline against a JSON failure fixture."""

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


def cmd_governed_explain(args):
    """Print an explanation of a stored governed run."""
    store = SQLiteGovernedStore(args.store) if args.store else SQLiteGovernedStore()
    print(explain_stored_run(store, args.run_id))
    return 0


def cmd_governed_replay(args):
    """Print a stored governed run and its events; exit 2 if not found."""
    store = SQLiteGovernedStore(args.store) if args.store else SQLiteGovernedStore()
    state = store.load_run(args.run_id)
    if state is None:
        print(json.dumps({"error": "run_not_found", "run_id": args.run_id}, indent=2))
        return 2
    events = store.list_events(args.run_id) if hasattr(store, "list_events") else ()
    _dump({"run": state, "events": list(events)})
    return 0


def cmd_governed_benchmark(args):
    """Run the governed synthetic benchmark suite; exit 2 if any case fails."""
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
            "policy_outcome": None if result.policy_outcome is None else result.policy_outcome.value,
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
    """Run the foundation-inspect command: print the state of a durable foundation run."""
    from ci_failure_orchestrator.foundation import inspect_run

    info = inspect_run(Path(args.artifacts), args.run_id)
    _dump(info.__dict__)
    return 0


def cmd_foundation_events(args):
    """Run the foundation-events command: print a foundation run's audit timeline, one event per line."""
    from ci_failure_orchestrator.foundation import replay_events

    for line in replay_events(Path(args.artifacts), args.run_id):
        print(line)
    return 0


def cmd_foundation_resume(args):
    """Run the foundation-resume command: print the resume decision for a durable run; exit 2 if INCONSISTENT."""
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


def cmd_foundation_decide(args):
    """Run the foundation-decide command: record a reviewer decision; exit 1 if BLOCKED, 2 if INCONSISTENT."""
    from ci_failure_orchestrator.foundation import apply_reviewer_decision

    result = apply_reviewer_decision(
        Path(args.artifacts),
        args.run_id,
        action=args.action,
        reviewer_id=args.reviewer or "",
        comment=args.comment or "",
        escalation_id=args.escalation_id,
    )
    _dump(
        {
            "status": result.status.value,
            "run_id": result.run_id,
            "workflow_status_before": result.workflow_status_before,
            "workflow_status_after": result.workflow_status_after,
            "action": result.action,
            "message": result.message,
            "last_sequence": result.last_sequence,
            "primary_workspace_mutated": result.primary_workspace_mutated,
        }
    )
    if result.status.value == "INCONSISTENT":
        return 2
    if result.status.value == "BLOCKED":
        return 1
    return 0


def cmd_foundation_verify(args):
    """Run the foundation-verify command: check a run's state and audit consistency; exit 2 if invalid."""
    from ci_failure_orchestrator.foundation import verify_run_consistency

    report = verify_run_consistency(artifacts_root=Path(args.artifacts), run_id=args.run_id)
    _dump(
        {
            "valid": report.valid,
            "issues": [{"code": i.code, "message": i.message} for i in report.issues],
        }
    )
    return 0 if report.valid else 2


_FIX_REPO_EXIT = {"APPROVED": 0, "NO_FAILURE": 0, "AWAITING_HUMAN": 3}


def cmd_fix_repo(args):
    """Run the fix-repo command: verify a patch; exit 0 if APPROVED or NO_FAILURE, 3 if AWAITING_HUMAN, else 2."""
    failure = None
    try:
        if args.github_repo or args.github_run_id:
            if not (args.github_repo and args.github_run_id):
                raise ValueError("--github-repo and --github-run-id must be used together")
            failure = failure_from_github(
                args.github_repo,
                args.github_run_id,
                token=args.github_token,
                api_url=args.github_api_url,
            )
        elif args.log_file:
            failure = failure_from_log_file(args.log_file)
        elif args.fixture:
            failure = failure_from_fixture(args.fixture)
    except Exception as exc:  # noqa: BLE001 - surface ingestion errors as structured output
        _dump({"outcome": "ERROR", "message": f"failure ingestion failed: {exc}", "primary_workspace_mutated": False})
        return 2
    try:
        raw = read_verification_config_file(Path(args.verification_config)) if args.verification_config else {}
        verification = load_verification_config(raw, regression=args.regression or ())
    except (OSError, ValueError, yaml.YAMLError) as exc:
        _dump(
            {"outcome": "ERROR", "message": f"invalid verification config: {exc}", "primary_workspace_mutated": False}
        )
        return 2

    outcome = run_fix_repo(
        FixRepoConfig(
            repo_path=Path(args.repo_path),
            verify_commands=args.verify,
            patch_file=Path(args.patch_file) if args.patch_file else None,
            provider_cmd=args.provider_cmd,
            provider_env=args.provider_env or (),
            provider_timeout=args.provider_timeout,
            verify_env=args.verify_env or (),
            verify_timeout=args.verify_timeout,
            container_image=args.container_image,
            base_ref=args.base_ref,
            max_attempts=args.max_attempts,
            artifacts_root=Path(args.artifacts),
            failure=failure,
            task_id=args.task_id,
            verification=verification,
        )
    )
    _dump(outcome)
    return _FIX_REPO_EXIT.get(outcome.get("outcome"), 2)


def cmd_fix_repo_verify_ci(args):
    """Run the fix-repo-verify-ci command: record real CI results; exit 0 VERIFIED_FIXED, 3 PENDING, 2 ERROR, else 1."""
    token = args.github_token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    try:
        provider = GitHubActionsCIProvider(
            args.repository, GitHubActionsClient(token=token, api_url=args.github_api_url, timeout=args.timeout)
        )
    except ValueError as exc:
        _dump({"outcome": "ERROR", "message": str(exc)})
        return 2
    outcome = verify_real_ci(
        Path(args.artifacts),
        args.run_id,
        provider,
        ci_run_ids=[str(r) for r in args.ci_run_id or ()],
        rerun=args.rerun,
        wait_seconds=args.wait,
        poll_seconds=args.poll_interval,
    )
    _dump(outcome)
    return {"VERIFIED_FIXED": 0, "PENDING": 3, "ERROR": 2}.get(outcome.get("outcome"), 1)


def cmd_fix_repo_metrics(args):
    """Run the fix-repo-metrics command: print remediation metrics for an artifacts directory."""
    artifacts = Path(args.artifacts)
    metrics = compute_remediation_metrics(load_remediation_records(artifacts))
    metrics["operational"] = compute_operational_metrics(load_run_measurements(artifacts))
    _dump(metrics)
    return 0


def cmd_fix_repo_task(args):
    """Run the fix-repo-task command: print a task with its runs and attempts; exit 2 if it cannot be loaded."""
    try:
        _dump(task_summary(Path(args.artifacts), args.task_id))
    except ValueError as exc:
        _dump({"outcome": "ERROR", "message": str(exc)})
        return 2
    return 0


def cmd_fix_repo_apply(args):
    """Run the fix-repo-apply command: commit an APPROVED patch to a new branch; exit 1 unless APPLIED or DRY_RUN."""
    result = apply_fix(
        Path(args.artifacts),
        args.run_id,
        repo_path=Path(args.repo_path) if args.repo_path else None,
        branch=args.branch,
        remote=args.remote,
        push=args.push,
        open_pr=args.open_pr,
        actor=args.actor,
        dry_run=args.dry_run,
    )
    if not args.dry_run and (Path(args.artifacts) / "runs" / args.run_id).is_dir():
        write_repair_evidence(Path(args.artifacts), args.run_id)
    _dump(result.to_dict())
    return 0 if result.status in ("APPLIED", "DRY_RUN") else 1


def cmd_fix_repo_report(args):
    """Run the fix-repo-report command: refresh and print a run's evidence report; exit 2 if the run is unknown."""
    if not (Path(args.artifacts) / "runs" / args.run_id).is_dir():
        _dump({"outcome": "ERROR", "message": f"unknown run: {args.run_id}"})
        return 2
    report = write_repair_evidence(Path(args.artifacts), args.run_id)
    if args.format == "json":
        _dump(report)
    else:
        print(render_repair_evidence_markdown(report), end="")
    return 0


def cmd_ci_audit_collect(args):
    """Run the ci-audit-collect command: write a read-only Actions export as JSON; exit 2 on API or input errors."""
    token = args.token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    client = GitHubActionsClient(token=token, api_url=args.api_url, timeout=args.timeout)
    try:
        export = collect_export(client, args.repo, days=args.days, max_runs=args.max_runs, max_logs=args.max_logs)
    except (GitHubAPIError, ValueError) as exc:
        _dump({"outcome": "ERROR", "message": str(exc)})
        return 2
    Path(args.output).write_text(json.dumps(export, indent=2), encoding="utf-8")
    _dump(
        {
            "outcome": "COLLECTED",
            "output": args.output,
            "runs": len(export["runs"]),
            "jobs": len(export["jobs"]),
            "failed_jobs": len(export["failures"]),
            "warnings": len(export["warnings"]),
            "authenticated": bool(token),
        }
    )
    return 0


def cmd_ci_audit_report(args):
    """Run the ci-audit-report command: render a Markdown report from an export; exit 2 if it cannot be read."""
    try:
        export = json.loads(Path(args.export).read_text(encoding="utf-8"))
        analysis = analyze_export(export)
    except (OSError, ValueError, KeyError) as exc:
        _dump({"outcome": "ERROR", "message": str(exc)})
        return 2
    Path(args.output).write_text(render_report(analysis), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    _dump(
        {
            "outcome": "REPORTED",
            "output": args.output,
            "findings": [f"{f['id']} {f['severity']}: {f['title']}" for f in analysis["findings"]],
        }
    )
    return 0



def build_parser():
    """Build the ``ci-orchestrator`` argument parser with every subcommand."""
    parser = argparse.ArgumentParser(
        prog="ci-orchestrator",
        description=(
            "Control plane for untrusted agent CI patches: diagnose (actions-doctor), "
            "ci-audit-*, fix-repo verify/policy/evidence, foundation-*, governed-*. "
            "Agents propose diffs; this tool verifies and never merges. "
            "See docs/CONTROL_PLANE.md."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("governed-run", help="Run governed pipeline on a failure fixture")
    run_cmd.add_argument("--fixture", required=True, help="JSON FailureEvent fixture")
    run_cmd.add_argument("--store", help="SQLite governed run store path")
    run_cmd.add_argument("--audit", help="Optional hash-chained audit JSONL path")
    run_cmd.set_defaults(func=cmd_governed_run)

    explain = sub.add_parser("governed-explain", help="Explain a stored governed run")
    explain.add_argument("run_id")
    explain.add_argument("--store", help="SQLite governed run store path")
    explain.set_defaults(func=cmd_governed_explain)

    replay = sub.add_parser("governed-replay", help="Replay stored governed run events")
    replay.add_argument("run_id")
    replay.add_argument("--store", help="SQLite governed run store path")
    replay.set_defaults(func=cmd_governed_replay)

    bench = sub.add_parser("governed-benchmark", help="Run governed synthetic benchmark suite")
    bench.add_argument(
        "--cases",
        default="benchmarks/cases",
        help="Directory of synthetic benchmark case JSON files",
    )
    bench.set_defaults(func=cmd_governed_benchmark)

    fb = sub.add_parser(
        "foundation-benchmark",
        help="Foundation golden benchmark (deterministic, synthetic)",
    )
    fb.add_argument("--cases", default="benchmarks/foundation/cases")
    fb.add_argument("--baseline", default="benchmarks/foundation/baselines/current.json")
    fb.add_argument("--artifacts", default="artifacts/benchmarks")
    fb.add_argument("--case", help="Filter by case_id")
    fb.add_argument("--category", help="Filter by category")
    fb.add_argument("--tag", help="Filter by tag")
    fb.add_argument("--required-only", action="store_true")
    fb.add_argument("--optional-only", action="store_true")
    fb.add_argument("--compare-baseline", action="store_true")
    fb.add_argument("--update-baseline", action="store_true")
    fb.set_defaults(func=cmd_foundation_benchmark)

    fops = sub.add_parser(
        "foundation-operations-report",
        help="Operational metrics/SLI/SLO report from retained runs",
    )
    fops.add_argument("--artifacts", default="artifacts")
    fops.add_argument("--output", default="artifacts/observability")
    fops.add_argument("--source", default="runtime", choices=["runtime", "benchmark"])
    fops.add_argument("--limit", type=int, default=None)
    fops.add_argument("--slo-config", default="config/slo.json")
    fops.set_defaults(func=cmd_foundation_operations_report)

    fslo = sub.add_parser("foundation-slo-check", help="SLO check (exit 1 if MISSED)")
    fslo.add_argument("--artifacts", default="artifacts")
    fslo.add_argument("--source", default="runtime", choices=["runtime", "benchmark"])
    fslo.add_argument("--limit", type=int, default=None)
    fslo.add_argument("--slo-config", default="config/slo.json")
    fslo.add_argument("--fail-insufficient", action="store_true")
    fslo.set_defaults(func=cmd_foundation_slo_check)

    foundation = sub.add_parser("foundation-run", help="Foundation pipeline; optional durable artifacts")
    foundation.add_argument("--fixture", required=True)
    foundation.add_argument("--artifacts")
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

    fd = sub.add_parser(
        "foundation-decide",
        help="Record human reviewer decision for AWAITING_HUMAN (APPROVE does not mutate primary workspace)",
    )
    fd.add_argument("run_id")
    fd.add_argument("--action", required=True, choices=["APPROVE", "REJECT", "REQUEST_CHANGES", "DEFER"])
    fd.add_argument("--reviewer", default="")
    fd.add_argument("--comment", default="")
    fd.add_argument("--escalation-id", default=None)
    fd.add_argument("--artifacts", default="artifacts")
    fd.set_defaults(func=cmd_foundation_decide)

    fv = sub.add_parser("foundation-verify", help="Verify foundation run state/audit consistency")
    fv.add_argument("run_id")
    fv.add_argument("--artifacts", default="artifacts")
    fv.set_defaults(func=cmd_foundation_verify)

    fix = sub.add_parser(
        "fix-repo",
        help=(
            "Verify an untrusted candidate patch for another git repo in a disposable worktree; "
            "run evaluation/retry/policy/escalation (never modifies the target repo; never merges)"
        ),
    )
    fix.add_argument("--repo-path", required=True)
    fix.add_argument("--verify", action="append", required=True, metavar="CMD")
    proposal = fix.add_mutually_exclusive_group(required=True)
    proposal.add_argument("--patch-file", help="Unified diff from a teammate or external agent")
    proposal.add_argument(
        "--provider-cmd",
        help='External agent CLI that reads stdin and prints a ```diff block (e.g. "claude -p")',
    )
    fix.add_argument("--provider-env", action="append", metavar="NAME")
    fix.add_argument("--provider-timeout", type=int, default=600)
    fix.add_argument("--verify-env", action="append", metavar="NAME")
    fix.add_argument("--verify-timeout", type=int, default=600)
    fix.add_argument("--container-image")
    source = fix.add_mutually_exclusive_group()
    source.add_argument("--github-repo")
    source.add_argument("--log-file")
    source.add_argument("--fixture")
    fix.add_argument("--github-run-id", type=int)
    fix.add_argument("--github-token")
    fix.add_argument("--github-api-url", default="https://api.github.com")
    fix.add_argument("--base-ref", default="HEAD")
    fix.add_argument("--max-attempts", type=int, default=3)
    fix.add_argument("--task-id")
    fix.add_argument("--regression", action="append", metavar="CMD")
    fix.add_argument("--verification-config", metavar="FILE")
    fix.add_argument("--artifacts", default="artifacts")
    fix.set_defaults(func=cmd_fix_repo)

    fixv = sub.add_parser(
        "fix-repo-verify-ci",
        help="Record real CI for an applied candidate and decide VERIFIED_FIXED",
    )
    fixv.add_argument("run_id")
    fixv.add_argument("--repository", required=True)
    fixv.add_argument("--ci-run-id", action="append")
    fixv.add_argument("--rerun", action="store_true")
    fixv.add_argument("--wait", type=int, default=0)
    fixv.add_argument("--poll-interval", type=int, default=15)
    fixv.add_argument("--github-token")
    fixv.add_argument("--github-api-url", default="https://api.github.com")
    fixv.add_argument("--timeout", type=float, default=30.0)
    fixv.add_argument("--artifacts", default="artifacts")
    fixv.set_defaults(func=cmd_fix_repo_verify_ci)

    fixm = sub.add_parser(
        "fix-repo-metrics",
        help="Verified repair rate is primary; CI green rate is shown for comparison",
    )
    fixm.add_argument("--artifacts", default="artifacts")
    fixm.set_defaults(func=cmd_fix_repo_metrics)

    fixr = sub.add_parser(
        "fix-repo-report",
        help="Evidence report: what broke, what changed, tests, safety, residual risk",
    )
    fixr.add_argument("run_id")
    fixr.add_argument("--format", choices=("md", "json"), default="md")
    fixr.add_argument("--artifacts", default="artifacts")
    fixr.set_defaults(func=cmd_fix_repo_report)

    fixt = sub.add_parser("fix-repo-task", help="Show a task with its runs and attempts (read-only)")
    fixt.add_argument("task_id")
    fixt.add_argument("--artifacts", default="artifacts")
    fixt.set_defaults(func=cmd_fix_repo_task)

    fixa = sub.add_parser(
        "fix-repo-apply",
        help="Commit an APPROVED patch to a new branch (draft PR at most; never merges)",
    )
    fixa.add_argument("run_id")
    fixa.add_argument("--artifacts", default="artifacts")
    fixa.add_argument("--repo-path")
    fixa.add_argument("--branch")
    fixa.add_argument("--remote", default="origin")
    fixa.add_argument("--push", action="store_true")
    fixa.add_argument("--open-pr", action="store_true")
    fixa.add_argument("--actor", default="operator")
    fixa.add_argument("--dry-run", action="store_true")
    fixa.set_defaults(func=cmd_fix_repo_apply)

    cac = sub.add_parser(
        "ci-audit-collect",
        help="Read-only: export GitHub Actions runs for one repository",
    )
    cac.add_argument("--repo", required=True)
    cac.add_argument("--days", type=int, default=30)
    cac.add_argument("--max-runs", type=int, default=500)
    cac.add_argument("--max-logs", type=int, default=50)
    cac.add_argument("--output", default="ci-audit-export.json")
    cac.add_argument("--token")
    cac.add_argument("--api-url", default="https://api.github.com")
    cac.add_argument("--timeout", type=float, default=30.0)
    cac.set_defaults(func=cmd_ci_audit_collect)

    car = sub.add_parser("ci-audit-report", help="Render a Markdown reliability report from a ci-audit export")
    car.add_argument("export")
    car.add_argument("--output", default="ci-audit-report.md")
    car.add_argument("--json")
    car.set_defaults(func=cmd_ci_audit_report)
    return parser


def main():
    """Parse the command line and run the chosen subcommand, returning its exit code."""
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

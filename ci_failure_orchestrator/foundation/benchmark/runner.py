"""BenchmarkRunner — isolated, deterministic foundation case execution."""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..classifier import FailureClassifier
from ..evaluator import LocalEvaluator
from ..models import FailureEvent, RepairProposal, new_id, utc_now as foundation_utc_now
from ..persistence import (
    AUDIT_SCHEMA,
    DURABLE_SCHEMA,
    AuditEvent,
    DurableRunState,
    FileAuditStore,
    FileEvidenceStore,
    FileStateStore,
    assess_recovery,
    resume_run,
)
from ..retry import RetryBudget, RetryReason
from ..runner import AgentExecutionFoundation, FoundationResult, ScriptedProposalFactory
from ..sandbox import TempCopySandboxExecutor
from ..tools import ToolValidationError, build_default_registry
from .assertions import (
    check_audit_artifacts,
    evaluate_expectations,
    scan_secrets_in_tree,
)
from .baseline import BaselineStore, CaseDelta, compare_to_baseline
from .injection import (
    BenchmarkInjectionError,
    maybe_wrap_evaluator,
    maybe_wrap_sandbox,
    write_fixture_workspace,
)
from .loader import filter_cases, load_suite
from .metrics import compute_suite_metrics
from .report import write_reports
from .schemas import (
    BENCHMARK_SCHEMA_VERSION,
    SUITE_VERSION,
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkMode,
    ObservedResult,
)


@dataclass
class BenchmarkSuiteResult:
    suite_run_id: str
    results: list[BenchmarkCaseResult]
    metrics: dict[str, Any]
    comparison: list[CaseDelta] = field(default_factory=list)
    report_paths: dict[str, Path] = field(default_factory=dict)
    exit_code: int = 0
    harness_errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_run_id": self.suite_run_id,
            "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
            "suite_version": SUITE_VERSION,
            "results": [r.to_dict() for r in self.results],
            "metrics": self.metrics,
            "comparison": [c.to_dict() for c in self.comparison],
            "exit_code": self.exit_code,
            "harness_errors": self.harness_errors,
        }


class BenchmarkRunner:
    """Execute golden cases against the foundation orchestrator."""

    def __init__(
        self,
        *,
        cases_dir: Path | None = None,
        baseline_path: Path | None = None,
        artifacts_root: Path | None = None,
        benchmark_mode: bool = True,
    ) -> None:
        if not benchmark_mode:
            raise BenchmarkInjectionError("BenchmarkRunner requires benchmark_mode=True")
        self.benchmark_mode = True
        self.cases_dir = Path(cases_dir) if cases_dir else None
        self.baseline_path = Path(baseline_path) if baseline_path else None
        self.artifacts_root = Path(artifacts_root) if artifacts_root else None

    def run_case(self, case: BenchmarkCase) -> BenchmarkCaseResult:
        started = time.perf_counter()
        tmp: tempfile.TemporaryDirectory[str] | None = None
        try:
            tmp = tempfile.TemporaryDirectory(prefix=f"bench-{case.case_id}-")
            work = Path(tmp.name)
            workspace = work / "workspace"
            artifacts = work / "artifacts"
            workspace.mkdir(parents=True)
            artifacts.mkdir(parents=True)
            write_fixture_workspace(workspace, case.fixture.workspace_files)

            if case.mode == BenchmarkMode.CLASSIFY.value:
                observed = self._run_classify(case)
            elif case.mode == BenchmarkMode.TOOL.value:
                observed = self._run_tool(case, workspace)
            elif case.mode == BenchmarkMode.RECOVERY.value:
                observed = self._run_recovery(case, artifacts)
            else:
                observed = self._run_orchestrator(case, workspace, artifacts)

            if observed.harness_error:
                duration = (time.perf_counter() - started) * 1000.0
                return BenchmarkCaseResult(
                    case_id=case.case_id,
                    passed=False,
                    duration_ms=duration,
                    assertions=[],
                    run_id=observed.run_id,
                    failure_reason=None,
                    harness_error=observed.harness_error,
                    required=case.required,
                    category=case.category,
                    tags=case.tags,
                    observed=_observed_dict(observed),
                    populations=case.expected.populations,
                )

            # Secret scan after run
            if case.expected.secrets_absent:
                leaked = scan_secrets_in_tree(artifacts, case.expected.secrets_absent)
                observed.secrets_leaked = leaked

            if case.expected.outside_path_absent:
                outside = Path(case.expected.outside_path_absent)
                if not outside.is_absolute():
                    outside = workspace.parent / outside
                observed.outside_path_exists = outside.exists()

            assertions = evaluate_expectations(case.expected, observed)
            passed = all(a.passed for a in assertions) if assertions else True
            failed = [a for a in assertions if not a.passed]
            duration = (time.perf_counter() - started) * 1000.0
            return BenchmarkCaseResult(
                case_id=case.case_id,
                passed=passed,
                duration_ms=duration,
                assertions=assertions,
                run_id=observed.run_id,
                failure_reason=(
                    "; ".join(f"{a.name}" for a in failed) if failed else None
                ),
                required=case.required,
                category=case.category,
                tags=case.tags,
                observed=_observed_dict(observed),
                populations=case.expected.populations,
                metrics={"duration_ms": duration},
            )
        except Exception as exc:  # noqa: BLE001
            duration = (time.perf_counter() - started) * 1000.0
            return BenchmarkCaseResult(
                case_id=case.case_id,
                passed=False,
                duration_ms=duration,
                assertions=[],
                harness_error=f"harness:{type(exc).__name__}: {exc}",
                required=case.required,
                category=case.category,
                tags=case.tags,
                populations=case.expected.populations,
            )
        finally:
            if tmp is not None:
                try:
                    tmp.cleanup()
                except OSError:
                    pass

    def run_suite(
        self,
        cases: list[BenchmarkCase] | None = None,
        *,
        case_id: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        required: bool | None = None,
        compare_baseline: bool = True,
        update_baseline: bool = False,
        preserve_artifacts: bool = True,
    ) -> BenchmarkSuiteResult:
        suite_run_id = f"bench-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        if cases is None:
            if self.cases_dir is None:
                raise BenchmarkInjectionError("cases_dir required when cases not provided")
            cases = load_suite(self.cases_dir)
        cases = filter_cases(
            cases,
            case_id=case_id,
            category=category,
            tag=tag,
            required=required,
        )

        results = [self.run_case(c) for c in cases]
        metrics = compute_suite_metrics(results)

        comparison: list[CaseDelta] = []
        baseline_store = None
        if self.baseline_path is not None:
            baseline_store = BaselineStore(self.baseline_path)
            if compare_baseline:
                comparison = compare_to_baseline(results, baseline_store.load())
            if update_baseline:
                baseline_store.write(results, metrics=metrics)

        report_paths: dict[str, Path] = {}
        if preserve_artifacts and self.artifacts_root is not None:
            out = self.artifacts_root / suite_run_id
            report_paths = write_reports(
                output_dir=out,
                suite_run_id=suite_run_id,
                results=results,
                metrics=metrics,
                comparison=comparison,
            )

        harness_errors = sum(1 for r in results if r.harness_error)
        required_failed = any(not r.passed and r.required for r in results)
        if harness_errors:
            exit_code = 2
        elif required_failed:
            exit_code = 1
        else:
            exit_code = 0
        # Also fail on regressions of previously passing required cases
        if exit_code == 0 and comparison:
            for delta in comparison:
                if delta.label.value != "REGRESSED":
                    continue
                match = next((r for r in results if r.case_id == delta.case_id), None)
                if match and match.required:
                    exit_code = 1
                    break

        return BenchmarkSuiteResult(
            suite_run_id=suite_run_id,
            results=results,
            metrics=metrics,
            comparison=comparison,
            report_paths=report_paths,
            exit_code=exit_code,
            harness_errors=harness_errors,
        )

    def _run_classify(self, case: BenchmarkCase) -> ObservedResult:
        event = FailureEvent.from_dict(case.fixture.event, run_id=new_id("run"))
        clf = FailureClassifier().classify(event)
        return ObservedResult(
            run_id=event.run_id,
            classification=clf.category,
            tools_used=(),
            security_signals=(),
        )

    def _run_tool(self, case: BenchmarkCase, workspace: Path) -> ObservedResult:
        registry = build_default_registry(root=workspace)
        tool_name = case.fixture.tool_name or ""
        args = dict(case.fixture.tool_arguments)
        signals: list[str] = []
        blocked = False
        subprocess_created = False
        try:
            if tool_name not in {t.name for t in registry.list_tools()}:
                blocked = True
                signals.append("unknown_tool_blocked")
                # Also attempt invoke to confirm registry raises
                try:
                    registry.invoke(new_id("run"), tool_name, args)
                except ToolValidationError:
                    pass
            else:
                call, result = registry.invoke(new_id("run"), tool_name, args)
                if not result.success:
                    blocked = True
                    if "path" in (result.stderr or "").lower() or "path" in str(
                        result.metadata
                    ):
                        signals.append("path_traversal_blocked")
                    signals.append("tool_execution_failed")
                tools_used = (tool_name,)
                return ObservedResult(
                    run_id=call.run_id,
                    tools_used=tools_used,
                    security_signals=tuple(signals),
                    tool_blocked=blocked or (not result.success),
                    subprocess_created=subprocess_created,
                )
        except ToolValidationError as exc:
            blocked = True
            msg = str(exc).lower()
            if "unknown tool" in msg:
                signals.append("unknown_tool_blocked")
            if "path" in msg or "out of scope" in msg:
                signals.append("path_traversal_blocked")
            signals.append("tool_validation_error")
        return ObservedResult(
            run_id=new_id("run"),
            tools_used=(),
            security_signals=tuple(dict.fromkeys(signals)),
            tool_blocked=blocked,
            subprocess_created=subprocess_created,
        )

    def _run_recovery(self, case: BenchmarkCase, artifacts: Path) -> ObservedResult:
        run_id = new_id("run")
        status = case.fixture.seed_workflow_status or "CLASSIFIED"
        store = FileStateStore(artifacts)
        audit = FileAuditStore(artifacts)
        evidence = FileEvidenceStore(artifacts)
        now = foundation_utc_now()
        state = DurableRunState(
            schema_version=DURABLE_SCHEMA,
            run_id=run_id,
            workflow_status=status,
            created_at=now,
            updated_at=now,
            current_attempt=0,
            last_event_sequence=0,
        )
        if case.fixture.seed_with_escalation:
            ref = evidence.write_text(
                run_id,
                "escalation",
                "# escalation\nreason: synthetic\n",
                name="summary.md",
            )
            state.evidence_index["escalation_summary_md"] = ref.ref
            state.escalation_ref = ref.ref
            eref = evidence.write_json(
                run_id,
                "evaluation",
                {"passed": True, "synthetic": True},
                name="evaluation.json",
            )
            state.evidence_index["evaluation"] = eref.ref
            state.latest_evaluation_ref = eref.ref
        store.create_run(state)
        audit.append(
            AuditEvent(
                schema_version=AUDIT_SCHEMA,
                event_id=new_id("evt"),
                run_id=run_id,
                sequence=1,
                timestamp=now,
                event_type="RUN_CREATED",
                actor="benchmark",
                component="benchmark.recovery",
                state_before=None,
                state_after=status,
            )
        )
        state.last_event_sequence = 1
        store.save_run(state)

        decision = assess_recovery(state)
        resume = resume_run(artifacts, run_id)
        return ObservedResult(
            run_id=run_id,
            recovery_status=decision.status.value,
            workflow_status=status,
            evidence_notes=[resume.message],
            artifacts_found=("state.json", "events.jsonl"),
            audit_complete=True,
        )

    def _run_orchestrator(
        self,
        case: BenchmarkCase,
        workspace: Path,
        artifacts: Path,
    ) -> ObservedResult:
        event = FailureEvent.from_dict(case.fixture.event, run_id=new_id("run"))
        proposals = _build_proposals(case, event.run_id)
        factory = ScriptedProposalFactory(proposals) if proposals else None

        sandbox: Any = TempCopySandboxExecutor(source_root=workspace)
        evaluator: Any = LocalEvaluator()
        injection = case.fixture.injection
        if injection is not None:
            sandbox = maybe_wrap_sandbox(
                sandbox, injection, benchmark_mode=self.benchmark_mode
            )
            evaluator = maybe_wrap_evaluator(
                evaluator, injection, benchmark_mode=self.benchmark_mode
            )

        budget_kwargs: dict[str, Any] = {"max_attempts": case.fixture.max_attempts}
        if case.fixture.max_identical_proposals is not None:
            budget_kwargs["max_identical_proposals"] = case.fixture.max_identical_proposals
        if case.fixture.max_identical_failures is not None:
            budget_kwargs["max_identical_failures"] = case.fixture.max_identical_failures
        if case.fixture.max_no_progress_attempts is not None:
            budget_kwargs["max_no_progress_attempts"] = case.fixture.max_no_progress_attempts

        agent = AgentExecutionFoundation(
            workspace_root=workspace,
            artifacts_root=artifacts if case.fixture.enable_persistence else None,
            proposal_factory=factory,
            target_pass_schedule=case.fixture.target_pass_schedule,
            retry_budget=RetryBudget(**budget_kwargs),
            force_forbidden_path=case.fixture.force_forbidden_path,
            force_target_fail=case.fixture.force_target_fail,
            sandbox=sandbox,
            evaluator=evaluator,
            enable_persistence=case.fixture.enable_persistence,
        )
        result = agent.run(event)
        return _observe_foundation(result, artifacts, case)


def _build_proposals(case: BenchmarkCase, run_id: str) -> list[RepairProposal]:
    out: list[RepairProposal] = []
    for item in case.fixture.proposals:
        if isinstance(item, str):
            out.append(
                RepairProposal(
                    proposal_id=new_id("prop"),
                    run_id=run_id,
                    files_changed=("src/app.py",),
                    patch=item,
                    rationale="synthetic",
                    expected_effect="fix",
                    verification_plan=("target_verification",),
                )
            )
            continue
        files = tuple(item.get("files") or ("src/app.py",))
        patch = str(item.get("patch") or f"--- a/x\n+++ b/x\n@@\n+# {new_id('fix')}\n")
        out.append(
            RepairProposal(
                proposal_id=new_id("prop"),
                run_id=run_id,
                files_changed=files,
                patch=patch,
                rationale=str(item.get("rationale") or "synthetic"),
                expected_effect=str(item.get("expected_effect") or "fix"),
                verification_plan=tuple(
                    item.get("verification_plan") or ("target_verification",)
                ),
            )
        )
    return out


def _observe_foundation(
    result: FoundationResult,
    artifacts: Path,
    case: BenchmarkCase,
) -> ObservedResult:
    run = result.run
    classification = run.classification.category if run.classification else None
    tools: list[str] = []
    if run.plan is not None:
        tools.extend(run.plan.required_tools)
        tools.extend(s.tool for s in run.plan.steps)

    progress = None
    duplicate = None
    if result.duplicate_proposal_count:
        duplicate = True
    if result.no_progress_count:
        progress = False
    if run.last_retry_decision:
        reason = str(run.last_retry_decision.get("reason") or "")
        if reason == RetryReason.IDENTICAL_PROPOSAL_REPEATED.value:
            duplicate = True
        if reason == RetryReason.NO_PROGRESS.value:
            progress = False
        if reason in {
            RetryReason.PARTIAL_PROGRESS.value,
            RetryReason.ALTERNATIVE_PLAN_AVAILABLE.value,
            RetryReason.RECOVERABLE_FAILURE.value,
        }:
            progress = True
    if result.stop_reason is RetryReason.IDENTICAL_PROPOSAL_REPEATED:
        duplicate = True
    if result.stop_reason is RetryReason.NO_PROGRESS:
        progress = False
    if result.retries and result.technical_status == "PASS":
        progress = True if progress is None else progress

    signals: list[str] = []
    if result.policy_outcome and result.policy_outcome.value == "REJECT":
        signals.append("policy_reject")
    if run.evaluation and run.evaluation.forbidden_changes_detected:
        signals.append("forbidden_path_blocked")
    if case.fixture.force_forbidden_path and result.technical_status == "FAIL":
        signals.append("forbidden_path_blocked")
    if result.stop_reason in {
        RetryReason.SECURITY_BOUNDARY_HIT,
        RetryReason.UNRECOVERABLE_FAILURE,
        RetryReason.INVALID_PROPOSAL,
    } and case.fixture.force_forbidden_path:
        signals.append("forbidden_path_blocked")
    log = ""
    if run.event:
        log = f"{run.event.log_excerpt}\n{run.event.message}"
    if "ignore previous instructions" in log.lower():
        signals.append("prompt_injection_fixture")
        if "shell" not in tools and "bash" not in tools:
            signals.append("no_unauthorized_tool")
    if run.context and run.context.redactions_applied > 0:
        signals.append("secret_redacted")
    if result.policy_outcome and result.policy_outcome.value in {"REJECT", "ESCALATE"}:
        if run.proposal and any(
            "secret" in p or p.startswith("auth/") or p.startswith(".github/workflows")
            for p in run.proposal.files_changed
        ):
            signals.append("sensitive_path_contained")

    esc_fields: list[str] = []
    escalation_present = result.escalation is not None
    if result.escalation is not None:
        esc = result.escalation
        for attr in (
            "reason_codes",
            "affected_files",
            "evaluation_summary",
            "policy_summary",
            "attempt_summary",
            "unresolved_questions",
            "reviewer_checklist",
            "evidence_refs",
        ):
            val = getattr(esc, attr, None)
            if val:
                esc_fields.append(attr)

    audit_complete = None
    artifacts_found: list[str] = []
    run_root = artifacts / "runs" / result.run.run_id
    if case.fixture.enable_persistence and run_root.exists():
        audit_complete, artifacts_found_t = check_audit_artifacts(run_root)
        artifacts_found = list(artifacts_found_t)
        esc_summary = run_root / "escalation" / "summary.md"
        if esc_summary.is_file():
            artifacts_found.append("summary.md")
        esc_json = run_root / "escalation" / "summary.json"
        if esc_json.is_file():
            artifacts_found.append("summary.json")

    stop = result.stop_reason.value if result.stop_reason else run.stop_reason
    policy = (
        result.policy_outcome.value
        if result.policy_outcome is not None
        else run.policy_outcome
    )
    return ObservedResult(
        run_id=run.run_id,
        classification=classification,
        technical_status=result.technical_status or run.technical_status,
        attempts=result.attempts,
        retries=result.retries,
        stop_reason=stop,
        policy_outcome=policy,
        workflow_status=result.workflow_status or result.status.value,
        progress_detected=progress,
        duplicate_proposal=duplicate,
        tools_used=tuple(dict.fromkeys(tools)),
        security_signals=tuple(dict.fromkeys(signals)),
        escalation_present=escalation_present,
        escalation_fields_present=tuple(esc_fields),
        audit_complete=audit_complete,
        artifacts_found=tuple(dict.fromkeys(artifacts_found)),
        artifact_refs=dict(result.artifact_refs or run.artifact_refs or {}),
    )


def _observed_dict(observed: ObservedResult) -> dict[str, Any]:
    return {
        "run_id": observed.run_id,
        "classification": observed.classification,
        "technical_status": observed.technical_status,
        "attempts": observed.attempts,
        "retries": observed.retries,
        "stop_reason": observed.stop_reason,
        "policy_outcome": observed.policy_outcome,
        "workflow_status": observed.workflow_status,
        "progress_detected": observed.progress_detected,
        "duplicate_proposal": observed.duplicate_proposal,
        "tools_used": list(observed.tools_used),
        "security_signals": list(observed.security_signals),
        "escalation_present": observed.escalation_present,
        "audit_complete": observed.audit_complete,
        "recovery_status": observed.recovery_status,
        "tool_blocked": observed.tool_blocked,
    }

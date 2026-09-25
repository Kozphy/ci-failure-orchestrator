"""Phase 2–8 foundation runner — bounded retry + Policy Gate; no human workflow."""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from .classifier import FailureClassifier
from .context import ContextBuilder
from .escalation import (
    EscalationArtifacts,
    EscalationArtifactWriter,
    HumanEscalation,
    HumanEscalationBuilder,
)
from .evaluator import Evaluator, LocalEvaluator
from .models import (
    FailureClassification,
    FailureEvent,
    RunState,
    RunStatus,
    ToolRiskLevel,
    new_id,
    utc_now,
)

# Phase 13 — optional observability (never critical to orchestration decisions)
from .observability.metrics import (
    MetricsRecorder,
    NullMetricsRecorder,
    SafeMetricsRecorder,
)
from .persistence import (
    AuditEventType,
    PersistenceError,
    RunPersistence,
)
from .planner import DeterministicPlanner, Planner
from .policy import (
    PolicyConfig,
    PolicyDecision,
    PolicyEngine,
    StaticPolicyEngine,
)
from .policy_gate import PolicyGateMixin
from .proposal_factories import ProposalFactory, ScriptedProposalFactory, default_proposal_factory
from .results import FoundationResult
from .retry import (
    AttemptRecord,
    RetryBudget,
    RetryContext,
    RetryDecision,
    RetryDecisionEngine,
    RetryReason,
    build_attempt_record,
    retry_history_summaries,
)
from .sandbox import SandboxExecutor, TempCopySandboxExecutor
from .state_machine import ALLOWED_TRANSITIONS, FoundationStateMachine
from .tools import ToolRegistry, build_default_registry

__all__ = [
    "AgentExecutionFoundation",
    "FoundationResult",
    "ProposalFactory",
    "ScriptedProposalFactory",
]


class AgentExecutionFoundation(PolicyGateMixin):
    """FailureEvent → EvaluationResult → PolicyDecision → (optional) HumanEscalation.

    Evaluation PASS is technical success only.
    Policy APPROVE does not apply the patch to the primary workspace.
    Policy ESCALATE builds a review package and stops at AWAITING_HUMAN.
    """

    def __init__(
        self,
        *,
        planner: Planner | None = None,
        registry: ToolRegistry | None = None,
        sandbox: SandboxExecutor | None = None,
        evaluator: Evaluator | None = None,
        policy_engine: PolicyEngine | None = None,
        policy_config: PolicyConfig | None = None,
        workspace_root: Path | None = None,
        force_target_fail: bool = False,
        force_forbidden_path: bool = False,
        retry_budget: RetryBudget | None = None,
        proposal_factory: ProposalFactory | None = None,
        target_pass_schedule: Sequence[bool] | None = None,
        artifacts_root: Path | None = None,
        escalation_builder: HumanEscalationBuilder | None = None,
        escalation_writer: EscalationArtifactWriter | None = None,
        enable_persistence: bool | None = None,
        metrics: MetricsRecorder | None = None,
        metrics_source: str = "runtime",
    ) -> None:
        self.classifier = FailureClassifier()
        self.context_builder = ContextBuilder()
        self.planner = planner or DeterministicPlanner()
        self.registry = registry or build_default_registry(root=workspace_root)
        self.sandbox = sandbox or TempCopySandboxExecutor(source_root=workspace_root)
        self.evaluator = evaluator or LocalEvaluator()
        self.policy_config = policy_config or PolicyConfig()
        self.policy_engine = policy_engine or StaticPolicyEngine(self.policy_config)
        self.force_target_fail = force_target_fail
        self.force_forbidden_path = force_forbidden_path
        self.retry_budget = retry_budget or RetryBudget()
        self.proposal_factory = proposal_factory or default_proposal_factory
        self.target_pass_schedule = (
            list(target_pass_schedule) if target_pass_schedule is not None else None
        )
        self.retry_engine = RetryDecisionEngine()
        self.artifacts_root = Path(artifacts_root) if artifacts_root is not None else None
        self.escalation_builder = escalation_builder or HumanEscalationBuilder()
        self.escalation_writer = escalation_writer or EscalationArtifactWriter(
            artifacts_root=self.artifacts_root
        )
        persist = enable_persistence if enable_persistence is not None else self.artifacts_root is not None
        self.persistence: RunPersistence | None = (
            RunPersistence(self.artifacts_root) if persist and self.artifacts_root is not None else None
        )
        # Metrics never authorize; SafeMetricsRecorder absorbs backend failures.
        if metrics is None:
            self.metrics: MetricsRecorder = NullMetricsRecorder()
        else:
            self.metrics = SafeMetricsRecorder(metrics)
        self.metrics_source = (
            metrics_source if metrics_source in {"runtime", "benchmark"} else "runtime"
        )

    def run(self, event: FailureEvent) -> FoundationResult:
        self._run_started_perf = time.perf_counter()
        sm = FoundationStateMachine(RunStatus.RECEIVED)
        run_id = event.run_id or new_id("run")
        event = FailureEvent.from_dict(event.to_dict(), run_id=run_id)
        state = RunState(run_id=run_id, status=sm.status, event=event, updated_at=utc_now())
        attempts: list[AttemptRecord] = []
        decisions: list[RetryDecision] = []
        classification: FailureClassification | None = None
        tools_used: list[str] = []
        tool_risks: list[ToolRiskLevel] = []
        journal = self.persistence

        try:
            if journal is not None:
                journal.start_run(run_id, RunStatus.RECEIVED.value)
                ref = journal.write_json("input", event.to_dict(), name="failure-event.json")
                journal.checkpoint(failure_event_ref=ref.ref)

            for attempt_number in range(1, self.retry_budget.max_attempts + 1):
                tools_used.clear()
                tool_risks.clear()
                retry_ctx: RetryContext | None = None
                if attempt_number > 1:
                    retry_ctx = RetryContext(
                        attempt_number=attempt_number,
                        prior_attempts=tuple(attempts),
                        failed_approaches=tuple(
                            a.plan_goal[:120] for a in attempts if not a.evaluation_passed
                        ),
                        latest_evaluation=state.evaluation,
                        budget=self.retry_budget,
                    )

                history = retry_history_summaries(
                    attempts,
                    limit=self.retry_budget.max_retry_history_entries,
                )
                context = self.context_builder.build(event, previous_attempts=history)
                if attempt_number == 1:
                    before = sm.status.value
                    sm.transition(RunStatus.CONTEXT_READY, "context_built")
                    self._audit(
                        journal,
                        AuditEventType.CONTEXT_BUILT,
                        state_before=before,
                        state_after=sm.status.value,
                    )
                state.context = context
                state.status = sm.status

                classification = self._resolve_classification(
                    event, classification, attempts, attempt_number, sm
                )
                state.classification = classification
                state.status = sm.status
                if journal is not None and attempt_number == 1:
                    cref = journal.write_json(
                        "classification",
                        {
                            "run_id": classification.run_id,
                            "category": classification.category,
                            "confidence": classification.confidence,
                            "uncertainty": classification.uncertainty,
                            "evidence": list(classification.evidence),
                        },
                        name="classification.json",
                    )
                    journal.checkpoint(
                        workflow_status=sm.status.value,
                        classification_ref=cref.ref,
                    )
                    self._audit(
                        journal,
                        AuditEventType.FAILURE_CLASSIFIED,
                        state_after=sm.status.value,
                        evidence_refs=(cref,),
                        metadata={"category": classification.category},
                    )

                if journal is not None:
                    self._audit(
                        journal,
                        AuditEventType.ATTEMPT_STARTED,
                        metadata={"attempt": attempt_number},
                    )
                    journal.checkpoint(current_attempt=attempt_number, workflow_status=sm.status.value)

                plan = self.planner.plan(context, classification, retry_ctx)
                if attempt_number == 1:
                    before = sm.status.value
                    sm.transition(RunStatus.PLANNED, "plan_created")
                elif sm.status is RunStatus.RETRYING:
                    before = sm.status.value
                    sm.transition(RunStatus.PLANNED, "replan")
                else:
                    before = sm.status.value
                state.plan = plan
                state.status = sm.status
                if journal is not None:
                    pref = journal.write_json(
                        "plan",
                        {
                            "run_id": plan.run_id,
                            "goal": plan.goal,
                            "assumptions": list(plan.assumptions),
                            "required_tools": list(plan.required_tools),
                            "risk_level": plan.risk_level,
                            "verification_steps": list(plan.verification_steps),
                        },
                        name=f"plan-{attempt_number:03d}.json",
                    )
                    journal.checkpoint(
                        workflow_status=sm.status.value,
                        current_plan_ref=pref.ref,
                    )
                    self._audit(
                        journal,
                        AuditEventType.PLAN_CREATED,
                        state_before=before,
                        state_after=sm.status.value,
                        evidence_refs=(pref,),
                    )

                before = sm.status.value
                sm.transition(RunStatus.EXECUTING, "tools")
                state.status = sm.status
                for step in plan.steps:
                    args = dict(step.inputs)
                    if step.tool == "log_reader" and not args.get("excerpt"):
                        args["excerpt"] = event.log_excerpt or event.message
                    if step.tool == "file_reader" and not args.get("path") and context.changed_paths:
                        args["path"] = context.changed_paths[0]
                    if step.tool == "test_runner" and self._target_should_fail(attempt_number):
                        args["force_fail"] = True
                    if journal is not None:
                        self._audit(
                            journal,
                            AuditEventType.TOOL_CALLED,
                            metadata={"tool": step.tool, "risk": step.risk_level.value},
                        )
                    call, tool_result = self.registry.invoke(run_id, step.tool, args)
                    tools_used.append(step.tool)
                    tool_risks.append(call.risk_level)
                    if journal is not None:
                        tref = journal.write_json(
                            "tool",
                            {
                                "tool": step.tool,
                                "success": tool_result.success,
                                "exit_code": tool_result.exit_code,
                                "stdout": (tool_result.stdout or "")[:2_000],
                                "stderr": (tool_result.stderr or "")[:1_000],
                            },
                            name=f"tool-{attempt_number:03d}-{step.tool}.json",
                        )
                        self._audit(
                            journal,
                            AuditEventType.TOOL_COMPLETED,
                            evidence_refs=(tref,),
                            metadata={
                                "tool": step.tool,
                                "success": tool_result.success,
                                "risk": call.risk_level.value,
                            },
                        )

                paths = context.changed_paths or ("src/module.py",)
                proposal = self.proposal_factory(
                    run_id=run_id,
                    plan=plan,
                    classification=classification,
                    attempt_number=attempt_number,
                    paths=paths,
                    force_forbidden_path=self.force_forbidden_path,
                )
                before = sm.status.value
                sm.transition(RunStatus.PROPOSAL_READY, "proposal_created")
                state.proposal = proposal
                state.status = sm.status
                if journal is not None:
                    prop_ref = journal.write_json(
                        "proposal",
                        {
                            "proposal_id": proposal.proposal_id,
                            "files_changed": list(proposal.files_changed),
                            "rationale": proposal.rationale,
                            "expected_effect": proposal.expected_effect,
                        },
                        name=f"proposal-{attempt_number:03d}.json",
                    )
                    patch_ref = journal.write_text(
                        "patch",
                        proposal.patch,
                        name=f"proposal-{attempt_number:03d}.patch",
                        max_chars=journal.limits.max_patch_chars,
                    )
                    journal.checkpoint(
                        workflow_status=sm.status.value,
                        current_proposal_ref=prop_ref.ref,
                    )
                    self._audit(
                        journal,
                        AuditEventType.PROPOSAL_CREATED,
                        state_before=before,
                        state_after=sm.status.value,
                        evidence_refs=(prop_ref, patch_ref),
                    )

                before = sm.status.value
                sm.transition(RunStatus.SANDBOX_RUNNING, "sandbox")
                state.status = sm.status
                if journal is not None:
                    self._audit(
                        journal,
                        AuditEventType.SANDBOX_STARTED,
                        state_before=before,
                        state_after=sm.status.value,
                    )
                sandbox = self.sandbox.execute(
                    proposal,
                    plan.verification_steps,
                    target_should_pass=not self._target_should_fail(attempt_number),
                )
                state.sandbox = sandbox
                if journal is not None:
                    sref = journal.write_json(
                        "sandbox",
                        {
                            "run_id": sandbox.run_id,
                            "proposal_id": sandbox.proposal_id,
                            "success": sandbox.success,
                            "patch_applied": sandbox.patch_applied,
                            "timeout": sandbox.timeout,
                            "error": sandbox.error,
                            "changed_files": list(sandbox.changed_files),
                        },
                        name=f"sandbox-{attempt_number:03d}.json",
                    )
                    self._audit(
                        journal,
                        AuditEventType.SANDBOX_COMPLETED,
                        evidence_refs=(sref,),
                        metadata={"success": sandbox.success},
                    )

                before = sm.status.value
                sm.transition(RunStatus.EVALUATING, "evaluate")
                state.status = sm.status
                evaluation = self.evaluator.evaluate(proposal=proposal, sandbox=sandbox)
                before = sm.status.value
                sm.transition(RunStatus.EVALUATED, "evaluated")
                state.evaluation = evaluation
                state.status = sm.status
                if journal is not None:
                    eref = journal.write_json(
                        "evaluation",
                        {
                            "run_id": evaluation.run_id,
                            "passed": evaluation.passed,
                            "patch_applied": evaluation.patch_applied,
                            "target_verification_passed": evaluation.target_verification_passed,
                            "forbidden_changes_detected": evaluation.forbidden_changes_detected,
                            "checks": [
                                {"name": c.name, "status": c.status.value, "detail": c.detail}
                                for c in evaluation.checks
                            ],
                        },
                        name=f"evaluation-{attempt_number:03d}.json",
                    )
                    journal.checkpoint(
                        workflow_status=sm.status.value,
                        latest_evaluation_ref=eref.ref,
                    )
                    self._audit(
                        journal,
                        AuditEventType.EVALUATION_COMPLETED,
                        state_before=before,
                        state_after=sm.status.value,
                        evidence_refs=(eref,),
                        metadata={"passed": evaluation.passed},
                    )

                previous = attempts[-1] if attempts else None
                record = build_attempt_record(
                    attempt_number=attempt_number,
                    plan_goal=plan.goal,
                    proposal=proposal,
                    evaluation=evaluation,
                    sandbox=sandbox,
                    event=event,
                    classification=classification,
                    previous=previous,
                )
                attempts.append(record)
                state.attempts = list(attempts)
                state.attempt_count = len(attempts)
                state.retry_count = max(0, len(attempts) - 1)
                if journal is not None:
                    journal.write_json(
                        "attempt",
                        {
                            "attempt_number": record.attempt_number,
                            "proposal_id": record.proposal_id,
                            "proposal_fingerprint": record.proposal_fingerprint,
                            "failure_fingerprint": record.failure_fingerprint,
                            "evaluation_passed": record.evaluation_passed,
                            "disposition": record.disposition.value,
                            "summary": record.summary,
                        },
                        name=f"attempt-{attempt_number:03d}.json",
                    )

                state.retry_trace.append(
                    f"Attempt {attempt_number}\n"
                    f"Result: {'PASS' if evaluation.passed else 'FAIL'}\n"
                    f"Proposal fp: {record.proposal_fingerprint[:12]}\n"
                    f"Failure fp: {record.failure_fingerprint[:12]}\n"
                    f"Progress: {bool(record.progress and record.progress.improved)}"
                )

                if evaluation.passed:
                    return self._run_policy_gate(
                        sm=sm,
                        state=state,
                        attempts=attempts,
                        decisions=decisions,
                        classification=classification,
                        proposal=proposal,
                        evaluation=evaluation,
                        tools_used=tuple(tools_used),
                        tool_risks=tuple(tool_risks),
                    )

                before = sm.status.value
                sm.transition(RunStatus.RETRY_DECISION, "evaluation_fail")
                state.status = sm.status
                decision = self.retry_engine.decide(
                    self.retry_budget,
                    attempts,
                    evaluation,
                )
                decisions.append(decision)
                state.last_retry_decision = {
                    "should_retry": decision.should_retry,
                    "reason": decision.reason.value,
                    "next_attempt": decision.next_attempt,
                    "budget_remaining": decision.budget_remaining,
                    "progress_detected": decision.progress_detected,
                    "evidence": list(decision.evidence),
                }
                state.retry_trace.append(
                    "Retry decision:\n"
                    f"{'RETRY' if decision.should_retry else 'STOP'}\n"
                    f"Why: {decision.reason.value}\n"
                    + "\n".join(f"- {e}" for e in decision.evidence if e)
                )
                if journal is not None:
                    rref = journal.write_json(
                        "retry",
                        state.last_retry_decision,
                        name=f"retry-decision-{attempt_number:03d}.json",
                    )
                    journal.checkpoint(
                        workflow_status=sm.status.value,
                        latest_retry_decision_ref=rref.ref,
                    )
                    self._audit(
                        journal,
                        AuditEventType.RETRY_DECIDED,
                        state_before=before,
                        state_after=sm.status.value,
                        evidence_refs=(rref,),
                        metadata={
                            "should_retry": decision.should_retry,
                            "reason": decision.reason.value,
                        },
                    )

                if not decision.should_retry:
                    before = sm.status.value
                    sm.transition(RunStatus.FAILED, decision.reason.value)
                    state.status = sm.status
                    state.stop_reason = decision.reason.value
                    state.technical_status = "FAIL"
                    state.updated_at = utc_now()
                    if journal is not None:
                        self._audit(
                            journal,
                            AuditEventType.RETRY_STOPPED,
                            state_before=before,
                            state_after=sm.status.value,
                            metadata={"reason": decision.reason.value},
                        )
                        self._audit(
                            journal,
                            AuditEventType.RUN_FAILED,
                            state_after=sm.status.value,
                        )
                        journal.checkpoint(
                            workflow_status=sm.status.value,
                            technical_status="FAIL",
                            stop_reason=decision.reason.value,
                        )
                    return self._result(
                        state,
                        attempts,
                        decisions,
                        decision.reason,
                        technical_status="FAIL",
                    )

                before = sm.status.value
                sm.transition(RunStatus.RETRYING, decision.reason.value)
                state.status = sm.status
                if journal is not None:
                    self._audit(
                        journal,
                        AuditEventType.RETRY_STARTED,
                        state_before=before,
                        state_after=sm.status.value,
                    )
                    journal.checkpoint(workflow_status=sm.status.value)

            if RunStatus.FAILED in ALLOWED_TRANSITIONS.get(sm.status, frozenset()):
                sm.transition(RunStatus.FAILED, RetryReason.MAX_ATTEMPTS_EXHAUSTED.value)
            state.status = RunStatus.FAILED
            state.stop_reason = RetryReason.MAX_ATTEMPTS_EXHAUSTED.value
            state.technical_status = "FAIL"
            state.updated_at = utc_now()
            if journal is not None:
                self._audit(journal, AuditEventType.RUN_FAILED, state_after=state.status.value)
                journal.checkpoint(
                    workflow_status=state.status.value,
                    technical_status="FAIL",
                    stop_reason=state.stop_reason,
                )
            return self._result(
                state,
                attempts,
                decisions,
                RetryReason.MAX_ATTEMPTS_EXHAUSTED,
                technical_status="FAIL",
            )
        except PersistenceError as exc:
            state.status = RunStatus.FAILED
            state.technical_status = "FAIL"
            state.stop_reason = f"PERSISTENCE_ERROR:{exc}"
            state.updated_at = utc_now()
            return self._result(
                state,
                attempts,
                decisions,
                RetryReason.UNRECOVERABLE_FAILURE,
                technical_status="FAIL",
            )
        except Exception as exc:  # noqa: BLE001
            if RunStatus.FAILED in ALLOWED_TRANSITIONS.get(sm.status, frozenset()):
                sm.transition(RunStatus.FAILED, f"error:{exc}")
                state.status = sm.status
            else:
                state.status = RunStatus.FAILED
            state.stop_reason = state.stop_reason or RetryReason.UNRECOVERABLE_FAILURE.value
            state.technical_status = "FAIL"
            state.updated_at = utc_now()
            state.attempts = list(attempts)
            state.attempt_count = len(attempts)
            state.retry_count = max(0, len(attempts) - 1)
            if journal is not None:
                try:
                    self._audit(
                        journal,
                        AuditEventType.RUN_FAILED,
                        state_after=state.status.value,
                        metadata={"error": type(exc).__name__},
                    )
                    journal.checkpoint(
                        workflow_status=state.status.value,
                        technical_status="FAIL",
                        stop_reason=state.stop_reason,
                    )
                except Exception:  # noqa: BLE001
                    pass
            return self._result(
                state,
                attempts,
                decisions,
                RetryReason.UNRECOVERABLE_FAILURE,
                technical_status="FAIL",
            )

    @staticmethod
    def _audit(
        journal: RunPersistence | None,
        event_type: AuditEventType,
        *,
        state_before: str | None = None,
        state_after: str | None = None,
        evidence_refs=(),
        metadata: dict | None = None,
    ) -> None:
        if journal is None:
            return
        journal.emit(
            event_type,
            state_before=state_before,
            state_after=state_after,
            evidence_refs=tuple(evidence_refs),
            metadata=metadata,
        )


    def _resolve_classification(
        self,
        event: FailureEvent,
        classification: FailureClassification | None,
        attempts: list[AttemptRecord],
        attempt_number: int,
        sm: FoundationStateMachine,
    ) -> FailureClassification:
        reclassify = classification is None
        if (
            not reclassify
            and attempt_number > 1
            and len(attempts) >= 2
            and attempts[-1].failure_fingerprint != attempts[-2].failure_fingerprint
        ):
            reclassify = True

        if reclassify or classification is None:
            classification = self.classifier.classify(event)
            if attempt_number == 1:
                sm.transition(RunStatus.CLASSIFIED, classification.category)
            return classification

        if attempt_number == 1:
            sm.transition(RunStatus.CLASSIFIED, classification.category)
        return classification

    def _target_should_fail(self, attempt_number: int) -> bool:
        if self.target_pass_schedule is not None:
            idx = min(attempt_number - 1, len(self.target_pass_schedule) - 1)
            return not self.target_pass_schedule[idx]
        return self.force_target_fail

    def _result(
        self,
        state: RunState,
        attempts: list[AttemptRecord],
        decisions: list[RetryDecision],
        stop_reason: RetryReason,
        *,
        technical_status: str,
        policy_decision: PolicyDecision | None = None,
        escalation: HumanEscalation | None = None,
        artifacts: EscalationArtifacts | None = None,
    ) -> FoundationResult:
        prop_counts: dict[str, int] = {}
        fail_counts: dict[str, int] = {}
        for a in attempts:
            prop_counts[a.proposal_fingerprint] = prop_counts.get(a.proposal_fingerprint, 0) + 1
            fail_counts[a.failure_fingerprint] = fail_counts.get(a.failure_fingerprint, 0) + 1
        dup_prop = sum(1 for c in prop_counts.values() if c > 1)
        dup_fail = sum(1 for c in fail_counts.values() if c > 1)
        no_prog = sum(
            1 for a in attempts if a.progress is not None and not a.progress.improved
        )
        artifact_refs = dict(state.artifact_refs)
        if artifacts is not None and not artifact_refs:
            artifact_refs = {
                "root": str(artifacts.root),
                "summary_json": str(artifacts.summary_json),
                "summary_md": str(artifacts.summary_md),
            }
        result = FoundationResult(
            run=state,
            status=state.status,
            attempts=len(attempts),
            retries=max(0, len(attempts) - 1),
            stop_reason=stop_reason,
            duplicate_proposal_count=dup_prop,
            duplicate_failure_count=dup_fail,
            no_progress_count=no_prog,
            decisions=list(decisions),
            technical_status=technical_status,
            policy_outcome=policy_decision.outcome if policy_decision else None,
            policy_decision=policy_decision,
            workflow_status=state.workflow_status or state.status.value,
            escalation=escalation or state.escalation,
            escalation_id=(escalation.escalation_id if escalation else state.escalation_id),
            artifact_refs=artifact_refs,
        )
        self._emit_run_metrics(result)
        return result

    def _emit_run_metrics(self, result: FoundationResult) -> None:
        duration = None
        started = getattr(self, "_run_started_perf", None)
        if started is not None:
            duration = time.perf_counter() - started
        try:
            # Lazy import avoids circular dependency with observability.recorder
            from .observability.recorder import record_foundation_run

            record_foundation_run(
                self.metrics,
                result,
                duration_seconds=duration,
                source=self.metrics_source,
                artifacts_root=self.artifacts_root,
                persist_summary=self.artifacts_root is not None,
            )
        except Exception:  # noqa: BLE001
            # Observability must never break orchestration
            pass

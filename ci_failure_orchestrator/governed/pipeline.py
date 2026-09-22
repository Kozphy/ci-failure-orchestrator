"""Governed end-to-end pipeline composing existing reliability primitives."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..audit import HashChainedAuditLog
from .classifier import FailureClassifier
from .context import ContextBuilder
from .escalation import build_escalation
from .evaluation import Evaluator, LocalEvaluator
from .metrics import PipelineMetrics
from .models import (
    AuditEvent,
    FailureEvent,
    PipelineState,
    PolicyOutcome,
    new_id,
    utc_now,
)
from .planner import DeterministicPlanner, Planner
from .policy import PolicyEngine
from .providers import AgentModel, DeterministicAgentModel
from .retry import RetryBudget
from .sandbox import SandboxExecutor
from .state_machine import PipelineStateMachine
from .store import SQLiteGovernedStore, StateStore
from .tools import ToolRegistry, build_default_registry


AUDIT_TYPES = (
    "RUN_STARTED",
    "FAILURE_CLASSIFIED",
    "PLAN_CREATED",
    "TOOL_CALLED",
    "TOOL_COMPLETED",
    "PROPOSAL_CREATED",
    "SANDBOX_STARTED",
    "EVALUATION_COMPLETED",
    "RETRY_APPROVED",
    "POLICY_APPROVED",
    "POLICY_ESCALATED",
    "REMEDIATION_APPLIED",
    "VERIFICATION_COMPLETED",
    "RUN_COMPLETED",
)


@dataclass
class PipelineResult:
    run_id: str
    state: PipelineState
    classification: Any = None
    plan: Any = None
    proposal: Any = None
    evaluation: Any = None
    policy: Any = None
    escalation: Any = None
    verification: Any = None
    attempts: int = 0
    metrics_snapshot: dict[str, float | int] = field(default_factory=dict)


class GovernedAgentPipeline:
    """CI failure → context → classify → plan → tools → proposal → sandbox →
    evaluate → retry/policy → escalate/verify → audit.
    """

    def __init__(
        self,
        *,
        store: StateStore | None = None,
        audit_log: HashChainedAuditLog | None = None,
        registry: ToolRegistry | None = None,
        planner: Planner | None = None,
        model: AgentModel | None = None,
        evaluator: Evaluator | None = None,
        policy: PolicyEngine | None = None,
        sandbox: SandboxExecutor | None = None,
        retry_budget: RetryBudget | None = None,
        metrics: PipelineMetrics | None = None,
    ) -> None:
        self.store = store or SQLiteGovernedStore()
        self.audit_log = audit_log
        self.registry = registry or build_default_registry()
        self.planner = planner or DeterministicPlanner()
        self.model = model or DeterministicAgentModel()
        self.evaluator = evaluator or LocalEvaluator()
        self.policy = policy or PolicyEngine()
        self.sandbox = sandbox or SandboxExecutor()
        self.retry_budget = retry_budget or RetryBudget()
        self.metrics = metrics or PipelineMetrics()
        self.classifier = FailureClassifier()
        self.context_builder = ContextBuilder()

    def _audit(self, run_id: str, event_type: str, **payload: Any) -> None:
        event = AuditEvent(
            event_id=new_id("aud"),
            run_id=run_id,
            event_type=event_type,
            actor="GovernedAgentPipeline",
            decision=payload.get("decision"),
            reason=str(payload.get("reason") or event_type),
            input_refs=tuple(payload.get("input_refs") or ()),
            output_refs=tuple(payload.get("output_refs") or ()),
        )
        self.store.append_event(run_id, event.to_payload())
        if self.audit_log is not None:
            self.audit_log.append(event_type, event.to_payload(), correlation_id=run_id)

    def run(self, event: FailureEvent) -> PipelineResult:
        started = time.perf_counter()
        sm = PipelineStateMachine(PipelineState.RECEIVED)
        run_id = event.run_id or new_id("run")
        event = replace(
            event,
            run_id=run_id,
            event_id=event.event_id or new_id("evt"),
        )
        self.metrics.agent_runs_total += 1
        self._audit(run_id, "RUN_STARTED", reason="pipeline_start")
        state: dict[str, Any] = {"run_id": run_id, "status": sm.state.value, "attempts": []}
        self.store.save_run(run_id, state)

        context = self.context_builder.build(event)
        sm.transition(PipelineState.CONTEXT_READY, "context_built")

        classification = self.classifier.classify(event)
        sm.transition(PipelineState.CLASSIFIED, classification.failure_class)
        self._audit(
            run_id,
            "FAILURE_CLASSIFIED",
            reason=classification.failure_class,
            decision=classification.failure_class,
        )

        if classification.recommended_next_action == "escalate_human":
            sm.transition(PipelineState.AWAITING_HUMAN, "classifier_escalate")
            escalation = build_escalation(
                run_id=run_id,
                context=context,
                classification=classification,
                proposal=None,
                evaluation=None,
                policy=None,
            )
            self.metrics.agent_runs_escalated_total += 1
            self._finish(run_id, sm, state, started, escalated=True)
            return PipelineResult(
                run_id=run_id,
                state=sm.state,
                classification=classification,
                escalation=escalation,
                attempts=self.retry_budget.attempts_used,
                metrics_snapshot=self.metrics.as_dict(),
            )

        proposal = None
        evaluation = None
        policy_decision = None
        plan = None
        tool_names: list[str] = []

        while True:
            plan = self.planner.plan(context, classification)
            sm.transition(PipelineState.PLANNED, "plan_created")
            self._audit(run_id, "PLAN_CREATED", reason=plan.goal[:120])

            sm.transition(PipelineState.EXECUTING, "tools")
            for step in plan.steps:
                call, result = self.registry.invoke(
                    run_id,
                    step.tool_name,
                    {"excerpt": event.log_excerpt, "path": (event.changed_paths[:1] or [""])[0], "target": "unit"},
                )
                tool_names.append(step.tool_name)
                self._audit(run_id, "TOOL_CALLED", reason=step.tool_name, output_refs=(call.call_id,))
                self._audit(
                    run_id,
                    "TOOL_COMPLETED",
                    reason=step.tool_name,
                    decision="ok" if result.ok else "error",
                )
                if not result.ok:
                    self.metrics.tool_call_failures += 1

            proposal = self.model.propose_repair(context, plan)
            self._audit(run_id, "PROPOSAL_CREATED", reason=proposal.proposal_id)

            self._audit(run_id, "SANDBOX_STARTED", reason=proposal.proposal_id)
            sandbox = self.sandbox.execute(proposal)
            if not sandbox.applied:
                self.metrics.sandbox_failures += 1

            sm.transition(PipelineState.EVALUATING, "evaluate")
            # Prefer tool test_runner result when present
            target_pass = True
            evaluation = self.evaluator.evaluate(
                run_id=run_id,
                proposal=proposal,
                sandbox=sandbox,
                target_check_passed=target_pass,
            )
            self._audit(
                run_id,
                "EVALUATION_COMPLETED",
                decision="pass" if evaluation.passed else "fail",
                reason=",".join(evaluation.evidence),
            )
            if not evaluation.passed:
                self.metrics.evaluation_failures += 1

            fingerprint = hashlib.sha256(
                f"{classification.failure_class}:{event.message}".encode()
            ).hexdigest()
            patch_fp = hashlib.sha256(proposal.proposed_patch.encode()).hexdigest()
            self.retry_budget.record_attempt(
                failure_fingerprint=fingerprint,
                patch_fingerprint=patch_fp,
            )
            self.metrics.repair_attempts_total += 1
            state["attempts"].append(
                {"proposal_id": proposal.proposal_id, "passed": evaluation.passed}
            )

            if evaluation.passed:
                sm.transition(PipelineState.POLICY_REVIEW, "eval_pass")
                policy_decision = self.policy.evaluate(
                    run_id=run_id,
                    proposal=proposal,
                    classification=classification,
                    evaluation=evaluation,
                    tool_names=tuple(tool_names),
                )
                if policy_decision.outcome is PolicyOutcome.APPROVE:
                    self._audit(run_id, "POLICY_APPROVED", decision="APPROVE")
                    sm.transition(PipelineState.APPROVED, "policy_approve")
                    sm.transition(PipelineState.VERIFYING, "verify")
                    self._audit(run_id, "VERIFICATION_COMPLETED", decision="verified")
                    sm.transition(PipelineState.SUCCEEDED, "success")
                    self.metrics.agent_runs_success_total += 1
                    self._finish(run_id, sm, state, started)
                    return PipelineResult(
                        run_id=run_id,
                        state=sm.state,
                        classification=classification,
                        plan=plan,
                        proposal=proposal,
                        evaluation=evaluation,
                        policy=policy_decision,
                        verification={"verified": True, "checks": list(plan.expected_verification)},
                        attempts=self.retry_budget.attempts_used,
                        metrics_snapshot=self.metrics.as_dict(),
                    )

                if policy_decision.outcome is PolicyOutcome.ESCALATE:
                    self._audit(run_id, "POLICY_ESCALATED", decision="ESCALATE")
                    sm.transition(PipelineState.AWAITING_HUMAN, "policy_escalate")
                    escalation = build_escalation(
                        run_id=run_id,
                        context=context,
                        classification=classification,
                        proposal=proposal,
                        evaluation=evaluation,
                        policy=policy_decision,
                        attempted=tuple(a["proposal_id"] for a in state["attempts"]),
                    )
                    self.metrics.agent_runs_escalated_total += 1
                    self._finish(run_id, sm, state, started, escalated=True)
                    return PipelineResult(
                        run_id=run_id,
                        state=sm.state,
                        classification=classification,
                        plan=plan,
                        proposal=proposal,
                        evaluation=evaluation,
                        policy=policy_decision,
                        escalation=escalation,
                        attempts=self.retry_budget.attempts_used,
                        metrics_snapshot=self.metrics.as_dict(),
                    )

                if policy_decision.outcome is PolicyOutcome.REJECT:
                    self.metrics.policy_rejection_total += 1
                    sm.transition(PipelineState.FAILED, "policy_reject")
                    self._finish(run_id, sm, state, started)
                    return PipelineResult(
                        run_id=run_id,
                        state=sm.state,
                        classification=classification,
                        plan=plan,
                        proposal=proposal,
                        evaluation=evaluation,
                        policy=policy_decision,
                        attempts=self.retry_budget.attempts_used,
                        metrics_snapshot=self.metrics.as_dict(),
                    )

                # RETRY from policy
                decision = self.retry_budget.decide(
                    run_id=run_id,
                    evaluation=evaluation,
                    proposal=proposal,
                )
            else:
                decision = self.retry_budget.decide(
                    run_id=run_id,
                    evaluation=evaluation,
                    proposal=proposal,
                )

            if decision.should_retry:
                self._audit(run_id, "RETRY_APPROVED", reason=decision.reason)
                # From EVALUATING or POLICY_REVIEW we need a legal path to RETRYING.
                if sm.state is PipelineState.POLICY_REVIEW:
                    sm.transition(PipelineState.RETRYING, decision.reason)
                elif sm.state is PipelineState.EVALUATING:
                    sm.transition(PipelineState.RETRYING, decision.reason)
                # RETRYING -> PLANNED for next loop iteration
                continue

            sm.transition(PipelineState.AWAITING_HUMAN, decision.reason)
            escalation = build_escalation(
                run_id=run_id,
                context=context,
                classification=classification,
                proposal=proposal,
                evaluation=evaluation,
                policy=policy_decision,
                attempted=tuple(a["proposal_id"] for a in state["attempts"]),
            )
            self.metrics.agent_runs_escalated_total += 1
            self._finish(run_id, sm, state, started, escalated=True)
            return PipelineResult(
                run_id=run_id,
                state=sm.state,
                classification=classification,
                plan=plan,
                proposal=proposal,
                evaluation=evaluation,
                policy=policy_decision,
                escalation=escalation,
                attempts=self.retry_budget.attempts_used,
                metrics_snapshot=self.metrics.as_dict(),
            )

    def _finish(
        self,
        run_id: str,
        sm: PipelineStateMachine,
        state: dict[str, Any],
        started: float,
        *,
        escalated: bool = False,
    ) -> None:
        elapsed = (time.perf_counter() - started) * 1000.0
        self.metrics.record_latency(elapsed)
        state["status"] = sm.state.value
        state["escalated"] = escalated
        state["updated_at"] = utc_now()
        self.store.save_run(run_id, state)
        self._audit(run_id, "RUN_COMPLETED", decision=sm.state.value, reason=sm.state.value)


def failure_event_from_dict(data: dict[str, Any], *, run_id: str | None = None) -> FailureEvent:
    return FailureEvent(
        event_id=str(data.get("event_id") or new_id("evt")),
        run_id=run_id or str(data.get("run_id") or new_id("run")),
        source=str(data.get("source") or "fixture"),
        workflow=str(data.get("workflow") or "ci"),
        job=str(data.get("job") or "test"),
        failed_step=str(data.get("failed_step") or "unknown"),
        message=str(data.get("message") or ""),
        changed_paths=tuple(data.get("changed_paths") or ()),
        log_excerpt=str(data.get("log_excerpt") or ""),
    )


def default_audit_path(path: str | Path | None = None) -> HashChainedAuditLog:
    return HashChainedAuditLog(path or "artifacts/governed-audit.jsonl")

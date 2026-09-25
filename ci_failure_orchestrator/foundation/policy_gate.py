"""Policy Gate stage of the foundation runner (evaluation PASS -> APPROVE / REJECT / ESCALATE)."""

from __future__ import annotations

from .escalation import EscalationArtifactWriter, HumanEscalationBuilder
from .models import FailureClassification, RepairProposal, RunState, RunStatus, ToolRiskLevel, utc_now
from .persistence import AuditEventType, RunPersistence
from .policy import PolicyConfig, PolicyEngine, PolicyOutcome, build_policy_context
from .results import FoundationResult
from .retry import AttemptRecord, RetryDecision, RetryReason
from .state_machine import ALLOWED_TRANSITIONS, FoundationStateMachine


class PolicyGateMixin:
    """``_run_policy_gate`` for ``AgentExecutionFoundation``.

    Relies on the runner's attributes and its ``_audit`` / ``_result`` methods.
    """

    persistence: RunPersistence | None
    policy_engine: PolicyEngine
    policy_config: PolicyConfig
    escalation_builder: HumanEscalationBuilder
    escalation_writer: EscalationArtifactWriter

    def _run_policy_gate(
        self,
        *,
        sm: FoundationStateMachine,
        state: RunState,
        attempts: list[AttemptRecord],
        decisions: list[RetryDecision],
        classification: FailureClassification | None,
        proposal: RepairProposal,
        evaluation,
        tools_used: tuple[str, ...],
        tool_risks: tuple[ToolRiskLevel, ...],
    ) -> FoundationResult:
        journal = self.persistence
        before = sm.status.value
        sm.transition(RunStatus.POLICY_REVIEW, "evaluation_pass")
        state.status = sm.status
        state.technical_status = "PASS"
        state.stop_reason = RetryReason.SUCCESS.value
        self._audit(
            journal,
            AuditEventType.POLICY_REVIEW_STARTED,
            state_before=before,
            state_after=sm.status.value,
        )

        policy_ctx = build_policy_context(
            proposal=proposal,
            evaluation=evaluation,
            classification=classification,
            tools_used=tools_used,
            tool_risk_levels=tool_risks,
            attempt_count=len(attempts),
            config=self.policy_config,
        )
        policy_decision = self.policy_engine.evaluate(policy_ctx)
        state.policy_decision = policy_decision
        state.policy_outcome = policy_decision.outcome.value
        state.policy_trace.append(policy_decision.explain())

        policy_ref = None
        if journal is not None:
            policy_ref = journal.write_json(
                "policy",
                {
                    "outcome": policy_decision.outcome.value,
                    "reasons": list(policy_decision.reasons),
                    "matched_rules": list(policy_decision.matched_rules),
                    "risk_level": policy_decision.risk_level.value,
                    "evidence": list(policy_decision.evidence),
                    "violations": [
                        {
                            "rule_id": v.rule_id,
                            "severity": v.severity,
                            "message": v.message,
                            "evidence": list(v.evidence),
                        }
                        for v in policy_decision.violations
                    ],
                },
                name="policy-decision.json",
            )
            journal.checkpoint(
                workflow_status=sm.status.value,
                technical_status="PASS",
                policy_outcome=policy_decision.outcome.value,
                latest_policy_decision_ref=policy_ref.ref,
            )

        outcome = policy_decision.outcome
        if outcome is PolicyOutcome.APPROVE:
            before = sm.status.value
            sm.transition(
                RunStatus.APPROVED,
                policy_decision.matched_rules[0] if policy_decision.matched_rules else "approve",
            )
            state.status = sm.status
            state.workflow_status = RunStatus.APPROVED.value
            state.updated_at = utc_now()
            self._audit(
                journal,
                AuditEventType.POLICY_APPROVED,
                state_before=before,
                state_after=sm.status.value,
                evidence_refs=(policy_ref,) if policy_ref else (),
                metadata={"rules": list(policy_decision.matched_rules)},
            )
            self._audit(journal, AuditEventType.RUN_SUCCEEDED, state_after=sm.status.value)
            if journal is not None:
                journal.checkpoint(workflow_status=sm.status.value, technical_status="PASS")
            return self._result(
                state,
                attempts,
                decisions,
                RetryReason.SUCCESS,
                technical_status="PASS",
                policy_decision=policy_decision,
            )

        if outcome is PolicyOutcome.REJECT:
            before = sm.status.value
            sm.transition(
                RunStatus.REJECTED,
                policy_decision.matched_rules[0] if policy_decision.matched_rules else "reject",
            )
            state.status = sm.status
            state.workflow_status = RunStatus.REJECTED.value
            state.updated_at = utc_now()
            self._audit(
                journal,
                AuditEventType.POLICY_REJECTED,
                state_before=before,
                state_after=sm.status.value,
                evidence_refs=(policy_ref,) if policy_ref else (),
                metadata={"rules": list(policy_decision.matched_rules)},
            )
            if journal is not None:
                journal.checkpoint(workflow_status=sm.status.value, technical_status="PASS")
            return self._result(
                state,
                attempts,
                decisions,
                RetryReason.SUCCESS,
                technical_status="PASS",
                policy_decision=policy_decision,
            )

        before = sm.status.value
        sm.transition(
            RunStatus.ESCALATED,
            policy_decision.matched_rules[0] if policy_decision.matched_rules else "escalate",
        )
        state.status = sm.status
        self._audit(
            journal,
            AuditEventType.POLICY_ESCALATED,
            state_before=before,
            state_after=sm.status.value,
            evidence_refs=(policy_ref,) if policy_ref else (),
            metadata={"rules": list(policy_decision.matched_rules)},
        )
        try:
            sm.transition(RunStatus.ESCALATION_BUILDING, "build_package")
            state.status = sm.status
            if journal is not None:
                journal.checkpoint(workflow_status=sm.status.value)
            escalation = self.escalation_builder.build(
                run_id=state.run_id,
                policy_decision=policy_decision,
                proposal=proposal,
                evaluation=evaluation,
                attempts=attempts,
                classification=classification,
                event=state.event,
                policy_context_categories=policy_ctx.file_categories,
                policy_context_scope=policy_ctx.change_scope,
            )
            artifacts = self.escalation_writer.write(
                escalation,
                proposal=proposal,
                evaluation=evaluation,
            )
            before = sm.status.value
            sm.transition(RunStatus.AWAITING_HUMAN, escalation.escalation_id)
            state.status = sm.status
            state.workflow_status = RunStatus.AWAITING_HUMAN.value
            state.escalation = escalation
            state.escalation_id = escalation.escalation_id
            state.artifact_refs = {
                "root": str(artifacts.root),
                "summary_json": str(artifacts.summary_json),
                "summary_md": str(artifacts.summary_md),
                "evidence_index": str(artifacts.evidence_index),
                "proposed_patch": str(artifacts.proposed_patch),
                "evaluation_summary": str(artifacts.evaluation_summary),
            }
            state.updated_at = utc_now()
            if journal is not None:
                eref = journal.write_json(
                    "escalation",
                    escalation.to_dict(),
                    name="summary.json",
                )
                journal.checkpoint(
                    workflow_status=sm.status.value,
                    escalation_ref=eref.ref,
                    technical_status="PASS",
                    policy_outcome=PolicyOutcome.ESCALATE.value,
                )
                self._audit(
                    journal,
                    AuditEventType.ESCALATION_PACKAGE_CREATED,
                    evidence_refs=(eref,),
                    metadata={
                        "escalation_id": escalation.escalation_id,
                        "completeness": escalation.evidence_completeness.status.value,
                    },
                )
                self._audit(
                    journal,
                    AuditEventType.AWAITING_HUMAN,
                    state_before=before,
                    state_after=sm.status.value,
                )
            return self._result(
                state,
                attempts,
                decisions,
                RetryReason.SUCCESS,
                technical_status="PASS",
                policy_decision=policy_decision,
                escalation=escalation,
                artifacts=artifacts,
            )
        except Exception as exc:  # noqa: BLE001 — fail closed, never APPROVE/REJECT
            if RunStatus.ESCALATION_ERROR in ALLOWED_TRANSITIONS.get(sm.status, frozenset()):
                sm.transition(RunStatus.ESCALATION_ERROR, f"escalation_failed:{exc}")
            state.status = RunStatus.ESCALATION_ERROR
            state.workflow_status = RunStatus.ESCALATION_ERROR.value
            state.updated_at = utc_now()
            state.policy_trace.append(f"escalation_package_failed: {type(exc).__name__}")
            if journal is not None:
                journal.checkpoint(workflow_status=state.status.value)
            return self._result(
                state,
                attempts,
                decisions,
                RetryReason.SUCCESS,
                technical_status="PASS",
                policy_decision=policy_decision,
            )

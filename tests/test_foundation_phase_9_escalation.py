"""Phase 9 — Human Escalation unit and integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci_failure_orchestrator.foundation import (
    AgentExecutionFoundation,
    EscalationArtifactWriter,
    FailureEvent,
    FoundationStateMachine,
    HumanEscalationBuilder,
    InvalidStateTransition,
    PolicyOutcome,
    ReviewerAction,
    RunStatus,
    ScriptedProposalFactory,
)
from ci_failure_orchestrator.foundation.escalation import (
    EscalationReasonCode,
    EvidenceCompletenessStatus,
    ReviewerDecision,
    build_checklist,
    map_reason_codes,
    render_escalation_markdown,
    validate_escalation_inputs,
)
from ci_failure_orchestrator.foundation.models import (
    CheckStatus,
    EvaluationCheck,
    EvaluationResult,
    FailureClassification,
    RepairProposal,
    new_id,
)
from ci_failure_orchestrator.foundation.policy import (
    RULE_AUTH_CHANGE,
    RULE_CI_WORKFLOW,
    RULE_DEPENDENCY_CHANGE,
    FileCategory,
    GovernanceRiskLevel,
    PolicyDecision,
)
from ci_failure_orchestrator.foundation.retry import RetryBudget
from ci_failure_orchestrator.foundation.sanitization import REDACTED
from ci_failure_orchestrator.foundation.state_machine import ALLOWED_TRANSITIONS


def _event(**kwargs) -> FailureEvent:
    base = dict(
        event_id=new_id("evt"),
        run_id=new_id("run"),
        source="synthetic",
        workflow="ci",
        job="test",
        failed_step="pytest",
        message="AssertionError: expected True",
        changed_paths=("src/app.py",),
        log_excerpt="FAILED tests/test_app.py::test_x",
        exit_code=1,
    )
    base.update(kwargs)
    return FailureEvent(**base)


def _eval(*, passed: bool = True) -> EvaluationResult:
    return EvaluationResult(
        run_id="r",
        passed=passed,
        patch_applied=True,
        target_verification_passed=passed,
        regressions_detected=False,
        forbidden_changes_detected=False,
        checks=(
            EvaluationCheck("PATCH_APPLIED", CheckStatus.PASSED),
            EvaluationCheck("TARGET_TEST_PASSED", CheckStatus.PASSED if passed else CheckStatus.FAILED),
            EvaluationCheck("RELEVANT_TESTS_PASSED", CheckStatus.UNAVAILABLE, "not_configured"),
        ),
        evidence=(),
    )


def _policy_escalate(*rules: str) -> PolicyDecision:
    return PolicyDecision(
        outcome=PolicyOutcome.ESCALATE,
        reasons=("test",),
        matched_rules=rules or (RULE_AUTH_CHANGE,),
        violations=(),
        risk_level=GovernanceRiskLevel.HIGH,
        evidence=("file:auth/x.py",),
    )


def _proposal(*files: str, patch: str = "--- a/x\n+++ b/x\n@@\n+#fix\n") -> RepairProposal:
    return RepairProposal(
        proposal_id=new_id("prop"),
        run_id="r",
        files_changed=files or ("auth/permissions.py",),
        patch=patch,
        rationale="Adjust role-checking logic",
        expected_effect="restore deny path",
        verification_plan=("target_verification",),
    )


# --- Domain ---


def test_human_escalation_serialization() -> None:
    builder = HumanEscalationBuilder()
    esc = builder.build(
        run_id="run-1",
        policy_decision=_policy_escalate(RULE_AUTH_CHANGE),
        proposal=_proposal("auth/permissions.py", "tests/test_permissions.py"),
        evaluation=_eval(),
        attempts=[],
        classification=FailureClassification(
            run_id="r",
            category="test_failure",
            evidence=(),
            confidence=0.5,
            uncertainty="h",
        ),
        event=_event(),
    )
    data = esc.to_dict()
    assert data["schema_version"]
    assert data["policy_outcome"] == "ESCALATE"
    assert "AUTHORIZATION_CHANGE" in data["reason_codes"]
    assert ReviewerAction.APPROVE.value in data["reviewer_actions"]
    md = render_escalation_markdown(esc)
    assert "# Human Review Required" in md
    assert "Available Reviewer Actions" in md
    assert "recommend" not in md.lower() or "does not recommend" in md.lower()


def test_reason_code_mapping() -> None:
    codes = map_reason_codes(_policy_escalate(RULE_CI_WORKFLOW), (FileCategory.CI,))
    assert EscalationReasonCode.CI_WORKFLOW_CHANGE in codes
    codes2 = map_reason_codes(_policy_escalate(RULE_DEPENDENCY_CHANGE), (FileCategory.DEPENDENCY,))
    assert EscalationReasonCode.DEPENDENCY_CHANGE in codes2


def test_reviewer_decision_future_facing() -> None:
    d = ReviewerDecision(escalation_id="esc-1", action=ReviewerAction.APPROVE, reviewer_id="alice")
    assert d.action is ReviewerAction.APPROVE


def test_missing_evidence_incomplete() -> None:
    c = validate_escalation_inputs(
        run_id="",
        policy_decision=None,
        proposal=None,
        evaluation=None,
        affected_files=None,
    )
    assert c.status is EvidenceCompletenessStatus.INCOMPLETE
    assert "run_id" in c.missing


def test_checklist_auth_and_ci() -> None:
    auth = build_checklist((EscalationReasonCode.AUTHORIZATION_CHANGE,))
    assert any("privilege" in i.lower() for i in auth)
    ci = build_checklist((EscalationReasonCode.CI_WORKFLOW_CHANGE,))
    assert any("workflow permissions" in i.lower() for i in ci)
    dep = build_checklist((EscalationReasonCode.DEPENDENCY_CHANGE,))
    assert any("lockfile" in i.lower() for i in dep)


def test_unknown_escalation_conservative_checklist() -> None:
    items = build_checklist((EscalationReasonCode.UNKNOWN_CHANGE_CATEGORY,))
    assert any("uncertainty" in i.lower() or "intent" in i.lower() for i in items)


# --- Artifact writer ---


def test_artifact_writer_sanitized(tmp_path: Path) -> None:
    secret_patch = (
        "--- a/auth/x.py\n+++ b/auth/x.py\n@@\n"
        "+# Authorization: Bearer secret-value-abc123\n"
        "+# password=example-secret\n"
        "+-----BEGIN PRIVATE KEY-----\nABC\n-----END PRIVATE KEY-----\n"
    )
    proposal = _proposal("auth/x.py", patch=secret_patch)
    evaluation = _eval()
    esc = HumanEscalationBuilder().build(
        run_id="esc-san",
        policy_decision=_policy_escalate(RULE_AUTH_CHANGE),
        proposal=proposal,
        evaluation=evaluation,
        attempts=[],
        event=_event(message="Authorization: Bearer leaky-token-value"),
    )
    arts = EscalationArtifactWriter(artifacts_root=tmp_path).write(
        esc, proposal=proposal, evaluation=evaluation
    )
    assert arts.summary_json.exists()
    assert arts.summary_md.exists()
    assert arts.evidence_index.exists()
    assert arts.proposed_patch.exists()
    patch_body = arts.proposed_patch.read_text(encoding="utf-8")
    assert "secret-value-abc123" not in patch_body
    assert "example-secret" not in patch_body
    assert "BEGIN PRIVATE KEY" not in patch_body or REDACTED in patch_body
    assert REDACTED in patch_body
    md = arts.summary_md.read_text(encoding="utf-8")
    assert "leaky-token-value" not in md
    payload = json.loads(arts.summary_json.read_text(encoding="utf-8"))
    assert payload["escalation_id"] == esc.escalation_id


def test_artifact_truncates_large_patch(tmp_path: Path) -> None:
    huge = "--- a/x\n+++ b/x\n@@\n" + ("+line\n" * 20_000)
    proposal = _proposal("src/x.py", patch=huge)
    esc = HumanEscalationBuilder().build(
        run_id="esc-big",
        policy_decision=_policy_escalate(RULE_AUTH_CHANGE),
        proposal=proposal,
        evaluation=_eval(),
        attempts=[],
    )
    arts = EscalationArtifactWriter(artifacts_root=tmp_path, max_patch_chars=500).write(
        esc, proposal=proposal, evaluation=_eval()
    )
    body = arts.proposed_patch.read_text(encoding="utf-8")
    assert "[truncated]" in body
    assert len(body) < 600


# --- State machine ---


def test_escalation_state_transitions() -> None:
    sm = FoundationStateMachine(RunStatus.POLICY_REVIEW)
    sm.transition(RunStatus.ESCALATED, "e")
    sm.transition(RunStatus.ESCALATION_BUILDING, "b")
    sm.transition(RunStatus.AWAITING_HUMAN, "a")
    assert sm.terminal
    with pytest.raises(InvalidStateTransition):
        FoundationStateMachine(RunStatus.AWAITING_HUMAN).transition(RunStatus.RETRYING, "no")
    assert RunStatus.AWAITING_HUMAN in ALLOWED_TRANSITIONS[RunStatus.ESCALATION_BUILDING]


# --- Integration ---


def test_integration_auth_awaiting_human(tmp_path: Path) -> None:
    result = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p",
                    run_id="p9-auth",
                    files_changed=("auth/session.py", "tests/test_session.py"),
                    patch="--- a/auth/session.py\n+++ b/auth/session.py\n@@\n+# auth\n",
                    rationale="auth fix",
                    expected_effect="pass",
                    verification_plan=("target_verification", "scope_check"),
                )
            ]
        ),
    ).run(_event(run_id="p9-auth", changed_paths=("auth/session.py",)))
    assert result.technical_status == "PASS"
    assert result.policy_outcome is PolicyOutcome.ESCALATE
    assert result.workflow_status == "AWAITING_HUMAN"
    assert result.status is RunStatus.AWAITING_HUMAN
    assert result.escalation is not None
    assert result.escalation_id
    assert (tmp_path / "runs" / "p9-auth" / "escalation" / "summary.md").exists()
    assert (tmp_path / "runs" / "p9-auth" / "escalation" / "summary.json").exists()
    checklist = "\n".join(result.escalation.reviewer_checklist)
    assert "privilege" in checklist.lower() or "authorization" in checklist.lower()


def test_integration_ci_checklist(tmp_path: Path) -> None:
    result = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p",
                    run_id="p9-ci",
                    files_changed=(".github/workflows/ci.yml",),
                    patch="--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n@@\n+# ci\n",
                    rationale="ci",
                    expected_effect="pass",
                    verification_plan=("target_verification", "scope_check"),
                )
            ]
        ),
    ).run(_event(run_id="p9-ci"))
    assert result.status is RunStatus.AWAITING_HUMAN
    assert any("workflow" in i.lower() for i in result.escalation.reviewer_checklist)


def test_integration_retry_then_escalation_history(tmp_path: Path) -> None:
    result = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        retry_budget=RetryBudget(max_attempts=3),
        target_pass_schedule=(False, True),
        proposal_factory=ScriptedProposalFactory(
            [
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+#1\n",
                RepairProposal(
                    proposal_id="p2",
                    run_id="p9-retry",
                    files_changed=("auth/permissions.py",),
                    patch="--- a/auth/permissions.py\n+++ b/auth/permissions.py\n@@\n+#2\n",
                    rationale="auth",
                    expected_effect="e",
                    verification_plan=("target_verification", "scope_check"),
                ),
            ]
        ),
    ).run(_event(run_id="p9-retry"))
    assert result.attempts == 2
    assert result.status is RunStatus.AWAITING_HUMAN
    assert "Attempt 1" in result.escalation.attempt_summary
    assert "Attempt 2" in result.escalation.attempt_summary


def test_integration_reject_no_escalation(tmp_path: Path) -> None:
    from ci_failure_orchestrator.foundation.models import SandboxResult, ToolResult

    class AllowGitSandbox:
        def execute(self, proposal, verification_steps, *, target_should_pass=True):
            return SandboxResult(
                run_id=proposal.run_id,
                proposal_id=proposal.proposal_id,
                success=True,
                patch_applied=True,
                command_results=(ToolResult("test_runner", True, 0, stdout="PASS"),),
                changed_files=proposal.files_changed,
            )

    class PassEvaluator:
        def evaluate(self, *, proposal, sandbox):
            return _eval(passed=True)

    result = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        sandbox=AllowGitSandbox(),
        evaluator=PassEvaluator(),
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p",
                    run_id="p9-rej",
                    files_changed=(".git/config",),
                    patch="diff",
                    rationale="bad",
                    expected_effect="x",
                    verification_plan=("target_verification",),
                )
            ]
        ),
    ).run(_event(run_id="p9-rej"))
    assert result.status is RunStatus.REJECTED
    assert result.escalation is None
    assert not (tmp_path / "runs" / "p9-rej" / "escalation").exists()


def test_integration_approve_no_escalation(tmp_path: Path) -> None:
    result = AgentExecutionFoundation(artifacts_root=tmp_path).run(_event(run_id="p9-ok"))
    assert result.status is RunStatus.APPROVED
    assert result.escalation is None
    assert not (tmp_path / "runs" / "p9-ok" / "escalation").exists()


def test_integration_sanitization_end_to_end(tmp_path: Path) -> None:
    result = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p",
                    run_id="p9-sec",
                    files_changed=("auth/token.py",),
                    patch=(
                        "--- a/auth/token.py\n+++ b/auth/token.py\n@@\n"
                        "+Authorization: Bearer secret-value\n"
                        "+password=example-secret\n"
                    ),
                    rationale="auth",
                    expected_effect="pass",
                    verification_plan=("target_verification", "scope_check"),
                )
            ]
        ),
    ).run(
        _event(
            run_id="p9-sec",
            message="failed with Authorization: Bearer secret-value password=example-secret",
        )
    )
    assert result.status is RunStatus.AWAITING_HUMAN
    patch = Path(result.artifact_refs["proposed_patch"]).read_text(encoding="utf-8")
    md = Path(result.artifact_refs["summary_md"]).read_text(encoding="utf-8")
    assert "secret-value" not in patch
    assert "example-secret" not in patch
    assert "secret-value" not in md
    assert REDACTED in patch or REDACTED in md

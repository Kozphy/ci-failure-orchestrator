"""Phase 8 — Policy Gate unit and integration tests."""

from __future__ import annotations

import pytest

from ci_failure_orchestrator.foundation import (
    AgentExecutionFoundation,
    FailureEvent,
    FoundationStateMachine,
    InvalidStateTransition,
    PolicyConfig,
    PolicyOutcome,
    RunStatus,
    ScriptedProposalFactory,
    StaticPolicyEngine,
)
from ci_failure_orchestrator.foundation.models import (
    CheckStatus,
    EvaluationCheck,
    EvaluationResult,
    FailureClassification,
    RepairProposal,
    SandboxResult,
    ToolResult,
    ToolRiskLevel,
    new_id,
)
from ci_failure_orchestrator.foundation.policy import (
    RULE_AUTH_CHANGE,
    RULE_CI_WORKFLOW,
    RULE_DEFAULT_ESCALATION,
    RULE_DEPENDENCY_CHANGE,
    RULE_ENGINE_FAILURE,
    RULE_EVALUATION_MUST_PASS,
    RULE_FORBIDDEN_PATH,
    RULE_LOW_RISK_AUTO_APPROVE,
    RULE_SECURITY_SENSITIVE,
    ChangeScope,
    FileCategory,
    GovernanceRiskLevel,
    PolicyContext,
    build_policy_context,
    classify_file,
    classify_risk,
    classify_scope,
)
from ci_failure_orchestrator.foundation.retry import RetryBudget
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


def _proposal(
    *files: str,
    patch: str = "--- a/x\n+++ b/x\n@@\n+# fix\n",
    run_id: str = "r",
) -> RepairProposal:
    return RepairProposal(
        proposal_id=new_id("prop"),
        run_id=run_id,
        files_changed=files or ("src/app.py",),
        patch=patch,
        rationale="r",
        expected_effect="e",
        verification_plan=("target_verification",),
    )


def _eval(*, passed: bool = True, forbidden: bool = False) -> EvaluationResult:
    return EvaluationResult(
        run_id="r",
        passed=passed,
        patch_applied=True,
        target_verification_passed=passed,
        regressions_detected=False,
        forbidden_changes_detected=forbidden,
        checks=(
            EvaluationCheck("PATCH_APPLIED", CheckStatus.PASSED),
            EvaluationCheck(
                "TARGET_TEST_PASSED",
                CheckStatus.PASSED if passed else CheckStatus.FAILED,
            ),
        ),
        evidence=(),
    )


def _classification() -> FailureClassification:
    return FailureClassification(
        run_id="r",
        category="test_failure",
        evidence=(),
        confidence=0.7,
        uncertainty="heuristic",
    )


def _ctx(
    *files: str,
    passed: bool = True,
    tools: tuple[str, ...] = (),
    risks: tuple[ToolRiskLevel, ...] = (),
    attempts: int = 1,
) -> PolicyContext:
    proposal = _proposal(*files)
    return build_policy_context(
        proposal=proposal,
        evaluation=_eval(passed=passed),
        classification=_classification(),
        tools_used=tools,
        tool_risk_levels=risks,
        attempt_count=attempts,
    )


# --- Config ---


def test_policy_config_defaults_conservative() -> None:
    cfg = PolicyConfig()
    assert cfg.default_outcome is PolicyOutcome.ESCALATE


def test_policy_config_rejects_approve_default() -> None:
    with pytest.raises(ValueError):
        PolicyConfig(default_outcome=PolicyOutcome.APPROVE)


def test_policy_config_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError):
        PolicyConfig(auto_approve_max_files=0)
    with pytest.raises(ValueError):
        PolicyConfig(small_scope_max_files=10, moderate_scope_max_files=3)
    with pytest.raises(ValueError):
        PolicyConfig(forbidden_paths=("../evil",))


# --- Path / scope / risk classification ---


@pytest.mark.parametrize(
    "path,expected",
    [
        ("src/parser.py", FileCategory.SOURCE),
        ("tests/test_parser.py", FileCategory.TEST),
        ("docs/guide.md", FileCategory.DOCUMENTATION),
        (".github/workflows/ci.yml", FileCategory.CI),
        ("requirements.txt", FileCategory.DEPENDENCY),
        ("poetry.lock", FileCategory.DEPENDENCY),
        ("auth/session.py", FileCategory.AUTH),
        ("infra/main.tf", FileCategory.INFRASTRUCTURE),
        ("migrations/001_init.sql", FileCategory.MIGRATION),
        ("weird/bin.dat", FileCategory.UNKNOWN),
    ],
)
def test_classify_file(path: str, expected: FileCategory) -> None:
    assert classify_file(path) is expected


def test_classify_scope_and_risk() -> None:
    assert classify_scope(("src/a.py",)) is ChangeScope.SMALL
    assert classify_scope(tuple(f"src/m{i}.py" for i in range(10))) is ChangeScope.BROAD
    risk = classify_risk(
        categories=(FileCategory.SOURCE, FileCategory.TEST),
        scope=ChangeScope.SMALL,
        tool_risks=(ToolRiskLevel.READ_ONLY,),
        files=("src/a.py", "tests/test_a.py"),
    )
    assert risk is GovernanceRiskLevel.LOW
    assert (
        classify_risk(
            categories=(FileCategory.AUTH,),
            scope=ChangeScope.SMALL,
            tool_risks=(),
            files=("auth/x.py",),
        )
        is GovernanceRiskLevel.HIGH
    )


# --- Policy engine ---


def test_low_risk_approve() -> None:
    engine = StaticPolicyEngine()
    d = engine.evaluate(_ctx("src/app.py", "tests/test_app.py"))
    assert d.outcome is PolicyOutcome.APPROVE
    assert RULE_LOW_RISK_AUTO_APPROVE in d.matched_rules


def test_forbidden_path_reject() -> None:
    engine = StaticPolicyEngine()
    d = engine.evaluate(_ctx(".env", "src/app.py"))
    assert d.outcome is PolicyOutcome.REJECT
    assert RULE_FORBIDDEN_PATH in d.matched_rules


def test_auth_escalate() -> None:
    engine = StaticPolicyEngine()
    d = engine.evaluate(_ctx("auth/permissions.py"))
    assert d.outcome is PolicyOutcome.ESCALATE
    assert RULE_AUTH_CHANGE in d.matched_rules or RULE_SECURITY_SENSITIVE in d.matched_rules


def test_ci_workflow_escalate() -> None:
    engine = StaticPolicyEngine()
    d = engine.evaluate(_ctx(".github/workflows/ci.yml"))
    assert d.outcome is PolicyOutcome.ESCALATE
    assert RULE_CI_WORKFLOW in d.matched_rules


def test_dependency_escalate() -> None:
    engine = StaticPolicyEngine()
    d = engine.evaluate(_ctx("pyproject.toml"))
    assert d.outcome is PolicyOutcome.ESCALATE
    assert RULE_DEPENDENCY_CHANGE in d.matched_rules


def test_unknown_scope_escalates() -> None:
    engine = StaticPolicyEngine()
    d = engine.evaluate(_ctx("vendor/blob.bin"))
    assert d.outcome is PolicyOutcome.ESCALATE


def test_evaluation_fail_never_approve() -> None:
    engine = StaticPolicyEngine()
    d = engine.evaluate(_ctx("src/app.py", passed=False))
    assert d.outcome is PolicyOutcome.REJECT
    assert RULE_EVALUATION_MUST_PASS in d.matched_rules


def test_fail_closed_on_engine_exception() -> None:
    class BoomEngine(StaticPolicyEngine):
        def _evaluate(self, context: PolicyContext):
            raise RuntimeError("boom")

    d = BoomEngine().evaluate(_ctx("src/app.py"))
    assert d.outcome is PolicyOutcome.ESCALATE
    assert RULE_ENGINE_FAILURE in d.matched_rules


def test_precedence_forbidden_overrides_auto_approve() -> None:
    engine = StaticPolicyEngine()
    # Would be auto-approve eligible except forbidden path present
    d = engine.evaluate(_ctx("src/app.py", "secrets/x"))
    assert d.outcome is PolicyOutcome.REJECT
    assert RULE_FORBIDDEN_PATH in d.matched_rules
    assert RULE_LOW_RISK_AUTO_APPROVE not in d.matched_rules


def test_precedence_security_overrides_auto_approve() -> None:
    engine = StaticPolicyEngine()
    d = engine.evaluate(_ctx("src/app.py", "auth/session.py"))
    assert d.outcome is PolicyOutcome.ESCALATE
    assert RULE_LOW_RISK_AUTO_APPROVE not in d.matched_rules


def test_default_escalation_when_no_allow() -> None:
    from ci_failure_orchestrator.foundation.policy import RULE_BROAD_SCOPE

    engine = StaticPolicyEngine(
        PolicyConfig(auto_approve_max_files=1)  # two files won't auto-approve
    )
    d = engine.evaluate(_ctx("src/a.py", "src/b.py", "src/c.py", "src/d.py"))
    assert d.outcome is PolicyOutcome.ESCALATE
    assert RULE_DEFAULT_ESCALATION in d.matched_rules or RULE_BROAD_SCOPE in d.matched_rules


# --- State machine ---


def test_policy_state_transitions() -> None:
    sm = FoundationStateMachine(RunStatus.EVALUATED)
    sm.transition(RunStatus.POLICY_REVIEW, "pass")
    sm.transition(RunStatus.APPROVED, "ok")
    assert sm.terminal

    sm2 = FoundationStateMachine(RunStatus.POLICY_REVIEW)
    sm2.transition(RunStatus.REJECTED, "no")
    sm3 = FoundationStateMachine(RunStatus.POLICY_REVIEW)
    sm3.transition(RunStatus.ESCALATED, "human")
    sm3.transition(RunStatus.ESCALATION_BUILDING, "build")
    sm3.transition(RunStatus.AWAITING_HUMAN, "ready")
    assert sm3.terminal
    assert RunStatus.SUCCEEDED not in ALLOWED_TRANSITIONS[RunStatus.EVALUATED]
    with pytest.raises(InvalidStateTransition):
        FoundationStateMachine(RunStatus.EVALUATED).transition(RunStatus.APPROVED, "skip")
    with pytest.raises(InvalidStateTransition):
        FoundationStateMachine(RunStatus.AWAITING_HUMAN).transition(RunStatus.RETRYING, "nope")


# --- Integration ---


def test_integration_low_risk_approve() -> None:
    result = AgentExecutionFoundation().run(_event(run_id="pol-approve"))
    assert result.technical_status == "PASS"
    assert result.policy_outcome is PolicyOutcome.APPROVE
    assert result.status is RunStatus.APPROVED
    assert result.policy_decision is not None
    assert RULE_LOW_RISK_AUTO_APPROVE in result.policy_decision.matched_rules


def test_integration_auth_escalate(tmp_path) -> None:
    result = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p",
                    run_id="pol-auth",
                    files_changed=("auth/session.py",),
                    patch="--- a/auth/session.py\n+++ b/auth/session.py\n@@\n+# auth fix\n",
                    rationale="auth",
                    expected_effect="pass",
                    verification_plan=("target_verification", "scope_check"),
                )
            ]
        ),
    ).run(_event(run_id="pol-auth", changed_paths=("auth/session.py",)))
    assert result.technical_status == "PASS"
    assert result.policy_outcome is PolicyOutcome.ESCALATE
    assert result.status is RunStatus.AWAITING_HUMAN
    assert result.workflow_status == RunStatus.AWAITING_HUMAN.value
    assert result.escalation is not None


def test_integration_forbidden_reject_with_fake_pass() -> None:
    """Technical PASS + policy-forbidden path (.git/) → REJECT without primary mutation."""

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
        sandbox=AllowGitSandbox(),
        evaluator=PassEvaluator(),
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p",
                    run_id="pol-rej",
                    files_changed=(".git/config",),
                    patch="--- a/.git/config\n+++ b/.git/config\n@@\n+# bad\n",
                    rationale="bad",
                    expected_effect="x",
                    verification_plan=("target_verification",),
                )
            ]
        ),
    ).run(_event(run_id="pol-rej"))
    assert result.technical_status == "PASS"
    assert result.policy_outcome is PolicyOutcome.REJECT
    assert result.status is RunStatus.REJECTED


def test_integration_ci_escalate(tmp_path) -> None:
    result = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p",
                    run_id="pol-ci",
                    files_changed=(".github/workflows/ci.yml",),
                    patch="--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n@@\n+# fix\n",
                    rationale="ci",
                    expected_effect="pass",
                    verification_plan=("target_verification", "scope_check"),
                )
            ]
        ),
    ).run(_event(run_id="pol-ci", changed_paths=(".github/workflows/ci.yml",)))
    assert result.technical_status == "PASS"
    assert result.policy_outcome is PolicyOutcome.ESCALATE
    assert result.status is RunStatus.AWAITING_HUMAN


def test_integration_retry_then_policy_approve() -> None:
    result = AgentExecutionFoundation(
        retry_budget=RetryBudget(max_attempts=3),
        target_pass_schedule=(False, True),
        proposal_factory=ScriptedProposalFactory(
            [
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+# try1\n",
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+# try2\n",
            ]
        ),
    ).run(_event(run_id="pol-retry-ok"))
    assert result.attempts == 2
    assert result.technical_status == "PASS"
    assert result.policy_outcome is PolicyOutcome.APPROVE
    assert result.status is RunStatus.APPROVED


def test_integration_retry_success_but_escalate(tmp_path) -> None:
    result = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        retry_budget=RetryBudget(max_attempts=3),
        target_pass_schedule=(False, True),
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p1",
                    run_id="pol-retry-esc",
                    files_changed=("src/app.py",),
                    patch="--- a/src/app.py\n+++ b/src/app.py\n@@\n+#1\n",
                    rationale="a",
                    expected_effect="e",
                    verification_plan=("target_verification", "scope_check"),
                ),
                RepairProposal(
                    proposal_id="p2",
                    run_id="pol-retry-esc",
                    files_changed=("auth/permissions.py",),
                    patch="--- a/auth/permissions.py\n+++ b/auth/permissions.py\n@@\n+#2\n",
                    rationale="auth",
                    expected_effect="e",
                    verification_plan=("target_verification", "scope_check"),
                ),
            ]
        ),
    ).run(_event(run_id="pol-retry-esc"))
    assert result.attempts == 2
    assert result.technical_status == "PASS"
    assert result.policy_outcome is PolicyOutcome.ESCALATE
    assert result.status is RunStatus.AWAITING_HUMAN
    assert result.escalation is not None
    assert "Attempt" in result.escalation.attempt_summary

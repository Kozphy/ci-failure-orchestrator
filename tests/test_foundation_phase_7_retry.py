"""Phase 7 — retry budget unit and integration tests."""

from __future__ import annotations

import pytest

from ci_failure_orchestrator.foundation import (
    AgentExecutionFoundation,
    FailureEvent,
    FoundationStateMachine,
    InvalidStateTransition,
    RunStatus,
    ScriptedProposalFactory,
)
from ci_failure_orchestrator.foundation.evaluator import LocalEvaluator
from ci_failure_orchestrator.foundation.models import (
    CheckStatus,
    EvaluationCheck,
    EvaluationResult,
    FailureClassification,
    RepairProposal,
    SandboxResult,
    ToolResult,
    new_id,
)
from ci_failure_orchestrator.foundation.retry import (
    AttemptRecord,
    FailureDisposition,
    ProgressAssessment,
    RetryBudget,
    RetryDecisionEngine,
    RetryReason,
    assess_progress,
    failure_fingerprint,
    normalize_patch,
    proposal_fingerprint,
)
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


def _proposal(patch: str, *, run_id: str = "r", files: tuple[str, ...] = ("src/a.py",)) -> RepairProposal:
    return RepairProposal(
        proposal_id=new_id("prop"),
        run_id=run_id,
        files_changed=files,
        patch=patch,
        rationale="r",
        expected_effect="e",
        verification_plan=("target_verification",),
    )


def _eval(
    *,
    passed: bool = False,
    patch_applied: bool = True,
    target: bool = False,
    forbidden: bool = False,
    failed_names: tuple[str, ...] = ("TARGET_TEST_PASSED",),
) -> EvaluationResult:
    checks = []
    for name in ("PATCH_APPLIED", "TARGET_TEST_PASSED", "NO_REGRESSIONS", "SCOPE_SAFE"):
        if name == "PATCH_APPLIED":
            status = CheckStatus.PASSED if patch_applied else CheckStatus.FAILED
        elif name == "TARGET_TEST_PASSED":
            status = CheckStatus.PASSED if target else CheckStatus.FAILED
        elif name in failed_names and not passed:
            status = CheckStatus.FAILED
        else:
            status = CheckStatus.PASSED if passed else CheckStatus.PASSED
        if name in failed_names and not passed and name != "PATCH_APPLIED":
            status = CheckStatus.FAILED
        checks.append(EvaluationCheck(name, status))
    return EvaluationResult(
        run_id="r",
        passed=passed,
        patch_applied=patch_applied,
        target_verification_passed=target,
        regressions_detected=False,
        forbidden_changes_detected=forbidden,
        checks=tuple(checks),
        evidence=(),
    )


def _attempt(
    n: int,
    *,
    prop_fp: str = "p1",
    fail_fp: str = "f1",
    passed: bool = False,
    failed_checks: int = 2,
    target: bool = False,
    patch_applied: bool = True,
    disposition: FailureDisposition = FailureDisposition.RECOVERABLE,
    progress: ProgressAssessment | None = None,
    sandbox_error: str | None = None,
) -> AttemptRecord:
    return AttemptRecord(
        attempt_number=n,
        plan_goal=f"goal-{n}",
        proposal_id=f"prop-{n}",
        proposal_fingerprint=prop_fp,
        failure_fingerprint=fail_fp,
        evaluation_passed=passed,
        patch_applied=patch_applied,
        target_passed=target,
        failed_check_count=failed_checks,
        sandbox_error=sandbox_error,
        disposition=disposition,
        progress=progress or ProgressAssessment(False, ("first_attempt",) if n == 1 else ()),
    )


# --- Budget ---


def test_budget_defaults_finite() -> None:
    b = RetryBudget()
    assert b.max_attempts >= 1
    assert b.max_attempts == 3


def test_budget_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        RetryBudget(max_attempts=0)
    with pytest.raises(ValueError):
        RetryBudget(max_identical_failures=0)
    with pytest.raises(ValueError):
        RetryBudget(max_identical_proposals=0)


# --- Fingerprints ---


def test_proposal_fingerprint_stable_and_sensitive() -> None:
    a = _proposal("--- a/x\n+++ b/x\n@@\n+line\n")
    b = _proposal("--- a/x\n+++ b/x\n@@\n+line\n")
    c = _proposal("--- a/x\n+++ b/x\n@@\n+other\n")
    assert proposal_fingerprint(a) == proposal_fingerprint(b)
    assert proposal_fingerprint(a) != proposal_fingerprint(c)


def test_proposal_fingerprint_ignores_unstable_metadata() -> None:
    p1 = _proposal("--- a/x\t2024-01-01T00:00:00\n+++ b/x\n@@\n+z\n")
    p2 = _proposal("--- a/x\t2099-12-31T99:99:99\n+++ b/x\n@@\n+z\n")
    assert normalize_patch(p1.patch) == normalize_patch(p2.patch)
    # files + normalized patch — timestamps stripped from ---/+++ lines
    assert proposal_fingerprint(p1) == proposal_fingerprint(p2)
    # Different proposal_id must not affect fingerprint
    assert p1.proposal_id != p2.proposal_id


def test_failure_fingerprint_stable_strips_noise() -> None:
    event = _event(
        message="AssertionError at /tmp/foo/bar 2024-01-01T12:00:00Z run-abc123",
        log_excerpt="FAILED tests/test_app.py::test_x",
    )
    event2 = _event(
        event_id=new_id("evt"),
        run_id=new_id("run"),
        message="AssertionError at /tmp/other/path 2099-01-01T01:01:01Z run-zzzzzz",
        log_excerpt="FAILED tests/test_app.py::test_x",
    )
    classification = FailureClassification(
        run_id="r",
        category="test_failure",
        evidence=(),
        confidence=0.5,
        uncertainty="heuristic",
    )
    ev = _eval(failed_names=("TARGET_TEST_PASSED",))
    fp1 = failure_fingerprint(event=event, classification=classification, evaluation=ev)
    fp2 = failure_fingerprint(event=event2, classification=classification, evaluation=ev)
    assert fp1 == fp2

    ev_other = _eval(failed_names=("TARGET_TEST_PASSED", "NO_REGRESSIONS"))
    fp3 = failure_fingerprint(event=event, classification=classification, evaluation=ev_other)
    assert fp1 != fp3


# --- Progress ---


def test_progress_target_fail_to_pass() -> None:
    prev = _attempt(1, target=False, failed_checks=2)
    cur = _attempt(2, target=True, failed_checks=1)
    p = assess_progress(prev, cur)
    assert p.improved
    assert "target_test_now_passes" in p.signals


def test_progress_fewer_failed_checks() -> None:
    prev = _attempt(1, failed_checks=4)
    cur = _attempt(2, failed_checks=2)
    assert assess_progress(prev, cur).improved


def test_progress_same_result_is_none() -> None:
    prev = _attempt(1, fail_fp="f", failed_checks=2, target=False)
    cur = _attempt(2, fail_fp="f", failed_checks=2, target=False)
    assert assess_progress(prev, cur).improved is False


def test_progress_sandbox_setup_to_ok() -> None:
    prev = _attempt(1, sandbox_error="sandbox_setup_error", patch_applied=False)
    cur = _attempt(2, sandbox_error=None, patch_applied=True)
    assert assess_progress(prev, cur).improved


def test_progress_different_error_alone_not_progress() -> None:
    prev = _attempt(1, fail_fp="a", failed_checks=2, patch_applied=True)
    cur = _attempt(2, fail_fp="b", failed_checks=2, patch_applied=True)
    assert assess_progress(prev, cur).improved is False


# --- Decision engine ---


def test_decide_success_stops() -> None:
    engine = RetryDecisionEngine()
    attempts = [_attempt(1, passed=True, progress=ProgressAssessment(True, ("ok",)))]
    d = engine.decide(RetryBudget(), attempts, _eval(passed=True, target=True))
    assert d.should_retry is False
    assert d.reason is RetryReason.SUCCESS


def test_decide_recoverable_retries() -> None:
    engine = RetryDecisionEngine()
    attempts = [_attempt(1, disposition=FailureDisposition.RECOVERABLE)]
    d = engine.decide(RetryBudget(max_attempts=3), attempts, _eval())
    assert d.should_retry is True
    assert d.reason in {
        RetryReason.RECOVERABLE_FAILURE,
        RetryReason.ALTERNATIVE_PLAN_AVAILABLE,
    }


def test_decide_max_attempts() -> None:
    engine = RetryDecisionEngine()
    budget = RetryBudget(max_attempts=2, max_no_progress_attempts=99, max_identical_failures=99)
    attempts = [
        _attempt(1, prop_fp="a", fail_fp="f1"),
        _attempt(2, prop_fp="b", fail_fp="f2", progress=ProgressAssessment(True, ("x",))),
    ]
    d = engine.decide(budget, attempts, _eval())
    assert d.should_retry is False
    assert d.reason is RetryReason.MAX_ATTEMPTS_EXHAUSTED


def test_decide_identical_proposal() -> None:
    engine = RetryDecisionEngine()
    budget = RetryBudget(max_identical_proposals=1, max_no_progress_attempts=99, max_identical_failures=99)
    attempts = [
        _attempt(1, prop_fp="same", fail_fp="f1"),
        _attempt(2, prop_fp="same", fail_fp="f2", progress=ProgressAssessment(True, ("x",))),
    ]
    d = engine.decide(budget, attempts, _eval())
    assert d.should_retry is False
    assert d.reason is RetryReason.IDENTICAL_PROPOSAL_REPEATED


def test_decide_identical_failure_no_progress() -> None:
    engine = RetryDecisionEngine()
    budget = RetryBudget(max_identical_failures=2, max_no_progress_attempts=99)
    attempts = [
        _attempt(1, prop_fp="a", fail_fp="same"),
        _attempt(2, prop_fp="b", fail_fp="same", progress=ProgressAssessment(False, ())),
    ]
    d = engine.decide(budget, attempts, _eval())
    assert d.should_retry is False
    assert d.reason is RetryReason.IDENTICAL_FAILURE_REPEATED


def test_decide_no_progress_streak() -> None:
    engine = RetryDecisionEngine()
    budget = RetryBudget(
        max_attempts=5,
        max_identical_failures=99,
        max_identical_proposals=99,
        max_no_progress_attempts=2,
    )
    attempts = [
        _attempt(1, prop_fp="a", fail_fp="f1"),
        _attempt(2, prop_fp="b", fail_fp="f2", progress=ProgressAssessment(False, ())),
    ]
    d = engine.decide(budget, attempts, _eval())
    assert d.should_retry is False
    assert d.reason is RetryReason.NO_PROGRESS


def test_decide_partial_progress_retries() -> None:
    engine = RetryDecisionEngine()
    budget = RetryBudget(max_attempts=5, max_identical_failures=99, max_no_progress_attempts=99)
    attempts = [
        _attempt(1, prop_fp="a", fail_fp="f1"),
        _attempt(
            2,
            prop_fp="b",
            fail_fp="f2",
            failed_checks=1,
            progress=ProgressAssessment(True, ("remaining_failure_count_decreased",)),
        ),
    ]
    d = engine.decide(budget, attempts, _eval())
    assert d.should_retry is True
    assert d.reason is RetryReason.PARTIAL_PROGRESS


def test_decide_unrecoverable() -> None:
    engine = RetryDecisionEngine()
    attempts = [
        _attempt(
            1,
            disposition=FailureDisposition.UNRECOVERABLE,
            sandbox_error="forbidden_path:x",
        )
    ]
    d = engine.decide(RetryBudget(), attempts, _eval(forbidden=True))
    assert d.should_retry is False
    assert d.reason in {RetryReason.UNRECOVERABLE_FAILURE, RetryReason.SECURITY_BOUNDARY_HIT}


def test_decide_unknown_conservative_stop() -> None:
    engine = RetryDecisionEngine()
    budget = RetryBudget(max_attempts=5, max_identical_failures=99, max_no_progress_attempts=99)
    attempts = [_attempt(1, disposition=FailureDisposition.UNKNOWN, progress=ProgressAssessment(False, ()))]
    d = engine.decide(budget, attempts, _eval())
    assert d.should_retry is False
    assert d.reason is RetryReason.INSUFFICIENT_EVIDENCE


# --- State machine ---


def test_retry_state_transitions() -> None:
    sm = FoundationStateMachine()
    for status, reason in [
        (RunStatus.CONTEXT_READY, "c"),
        (RunStatus.CLASSIFIED, "cl"),
        (RunStatus.PLANNED, "p"),
        (RunStatus.EXECUTING, "e"),
        (RunStatus.PROPOSAL_READY, "pr"),
        (RunStatus.SANDBOX_RUNNING, "s"),
        (RunStatus.EVALUATING, "ev"),
        (RunStatus.EVALUATED, "done"),
        (RunStatus.RETRY_DECISION, "decide"),
        (RunStatus.RETRYING, "retry"),
        (RunStatus.PLANNED, "replan"),
    ]:
        sm.transition(status, reason)
    with pytest.raises(InvalidStateTransition):
        FoundationStateMachine(RunStatus.EVALUATED).transition(RunStatus.RETRYING, "skip")
    assert RunStatus.RETRY_DECISION in ALLOWED_TRANSITIONS[RunStatus.EVALUATED]
    assert RunStatus.POLICY_REVIEW in ALLOWED_TRANSITIONS[RunStatus.EVALUATED]
    assert RunStatus.RETRYING in ALLOWED_TRANSITIONS[RunStatus.RETRY_DECISION]
    assert RunStatus.FAILED in ALLOWED_TRANSITIONS[RunStatus.RETRY_DECISION]


# --- Integration ---


def test_integration_success_on_second_attempt() -> None:
    foundation = AgentExecutionFoundation(
        retry_budget=RetryBudget(max_attempts=3),
        target_pass_schedule=(False, True),
        proposal_factory=ScriptedProposalFactory(
            [
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+# try1\n",
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+# try2\n",
            ]
        ),
    )
    result = foundation.run(_event(run_id="retry-success"))
    assert result.status is RunStatus.APPROVED
    assert result.technical_status == "PASS"
    assert result.attempts == 2
    assert result.retries == 1
    assert result.stop_reason is RetryReason.SUCCESS


def test_integration_identical_proposal_loop_stops() -> None:
    same = "--- a/src/app.py\n+++ b/src/app.py\n@@\n+# same\n"
    foundation = AgentExecutionFoundation(
        force_target_fail=True,
        retry_budget=RetryBudget(
            max_attempts=5,
            max_identical_proposals=1,
            max_identical_failures=99,
            max_no_progress_attempts=99,
        ),
        proposal_factory=ScriptedProposalFactory([same, same, same]),
    )
    result = foundation.run(_event(run_id="dup-prop"))
    assert result.status is RunStatus.FAILED
    assert result.stop_reason is RetryReason.IDENTICAL_PROPOSAL_REPEATED
    assert result.attempts == 2
    assert result.attempts < 5


def test_integration_no_progress_stops() -> None:
    foundation = AgentExecutionFoundation(
        force_target_fail=True,
        retry_budget=RetryBudget(
            max_attempts=5,
            max_identical_failures=99,
            max_identical_proposals=99,
            max_no_progress_attempts=2,
        ),
        proposal_factory=ScriptedProposalFactory(
            [
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+# a\n",
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+# b\n",
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+# c\n",
            ]
        ),
    )
    result = foundation.run(_event(run_id="no-prog"))
    assert result.status is RunStatus.FAILED
    assert result.stop_reason is RetryReason.NO_PROGRESS
    assert result.attempts == 2


def test_integration_max_attempts() -> None:
    foundation = AgentExecutionFoundation(
        force_target_fail=True,
        retry_budget=RetryBudget(
            max_attempts=3,
            max_identical_failures=99,
            max_identical_proposals=99,
            max_no_progress_attempts=99,
        ),
        proposal_factory=ScriptedProposalFactory(
            [
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+#1\n",
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+#2\n",
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+#3\n",
            ]
        ),
    )
    result = foundation.run(_event(run_id="max-att"))
    assert result.status is RunStatus.FAILED
    assert result.stop_reason is RetryReason.MAX_ATTEMPTS_EXHAUSTED
    assert result.attempts == 3
    assert result.retries == 2


def test_integration_unrecoverable_no_retry() -> None:
    foundation = AgentExecutionFoundation(
        force_forbidden_path=True,
        retry_budget=RetryBudget(max_attempts=3),
    )
    result = foundation.run(_event(run_id="unrec", message="ruff check failed", job="lint", failed_step="ruff"))
    assert result.status is RunStatus.FAILED
    assert result.attempts == 1
    assert result.stop_reason in {
        RetryReason.UNRECOVERABLE_FAILURE,
        RetryReason.SECURITY_BOUNDARY_HIT,
        RetryReason.INVALID_PROPOSAL,
    }


def test_integration_transient_then_success() -> None:
    class TransientThenOkSandbox:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, proposal, verification_steps, *, target_should_pass=True):
            self.calls += 1
            if self.calls == 1:
                return SandboxResult(
                    run_id=proposal.run_id,
                    proposal_id=proposal.proposal_id,
                    success=False,
                    patch_applied=False,
                    command_results=(),
                    changed_files=(),
                    timeout=True,
                    error="sandbox_setup_error:transient",
                )
            return SandboxResult(
                run_id=proposal.run_id,
                proposal_id=proposal.proposal_id,
                success=True,
                patch_applied=True,
                command_results=(ToolResult("test_runner", True, 0, stdout="PASS"),),
                changed_files=proposal.files_changed,
            )

    foundation = AgentExecutionFoundation(
        sandbox=TransientThenOkSandbox(),
        evaluator=LocalEvaluator(),
        retry_budget=RetryBudget(max_attempts=3, max_no_progress_attempts=99, max_identical_failures=99),
        proposal_factory=ScriptedProposalFactory(
            [
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+#t1\n",
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+#t2\n",
            ]
        ),
    )
    result = foundation.run(_event(run_id="transient"))
    assert result.status is RunStatus.APPROVED
    assert result.technical_status == "PASS"
    assert result.attempts == 2
    assert result.retries == 1


def test_phase6_compat_simple_pass() -> None:
    result = AgentExecutionFoundation().run(_event(run_id="compat-pass"))
    assert result.status is RunStatus.APPROVED
    assert result.technical_status == "PASS"
    assert result.attempts == 1
    assert result.retries == 0

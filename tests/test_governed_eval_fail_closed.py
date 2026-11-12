"""Fail-closed evaluation boundary regression tests. No network or paid model calls."""
from ci_failure_orchestrator.governed.evaluation import EvalForgeAdapter
from ci_failure_orchestrator.governed.models import RepairProposal, SandboxResult


def _proposal(files=("src/main.py",)):
    return RepairProposal(
        proposal_id="p1", run_id="r1", files_affected=files,
        proposed_patch="", reasoning_summary="", expected_impact="",
        risk_classification="low", verification_plan=(), rollback="",
    )


def _sandbox(*, applied=True, timed_out=False):
    return SandboxResult(
        run_id="r1", proposal_id="p1", applied=applied,
        commands_run=(), stdout_excerpt="", stderr_excerpt="", timed_out=timed_out,
    )


def _eval(remote, *, proposal=None, sandbox=None, target=True):
    adapter = EvalForgeAdapter(submit=lambda payload: "handle", fetch=lambda handle: remote)
    return adapter.evaluate(
        run_id="r1", proposal=proposal or _proposal(),
        sandbox=sandbox or _sandbox(), target_check_passed=target,
    )


def test_complete_remote_verdict_and_local_checks_pass():
    result = _eval(dict(passed=True, target_check_passed=True, regression_free=True,
                        policy_safe=True, evidence=["remote fixture"]))
    assert result.passed is True
    assert "remote fixture" in result.evidence


def test_missing_remote_policy_and_regression_fail_closed():
    result = _eval(dict(passed=True, target_check_passed=True))
    assert result.passed is False
    assert result.policy_safe is False
    assert result.regression_free is False


def test_remote_string_true_never_counts_as_boolean_approval():
    result = _eval(dict(passed="true", target_check_passed=True,
                        regression_free=True, policy_safe=True))
    assert result.passed is False


def test_remote_cannot_override_failed_local_test():
    result = _eval(dict(passed=True, target_check_passed=True,
                        regression_free=True, policy_safe=True), target=False)
    assert result.passed is False
    assert result.target_check_passed is False


def test_remote_cannot_override_sensitive_path_policy():
    result = _eval(dict(passed=True, target_check_passed=True,
                        regression_free=True, policy_safe=True),
                   proposal=_proposal((".github/workflows/deploy.yml",)))
    assert result.passed is False
    assert result.policy_safe is False


def test_remote_cannot_override_unapplied_sandbox():
    result = _eval(dict(passed=True, target_check_passed=True,
                        regression_free=True, policy_safe=True),
                   sandbox=_sandbox(applied=False))
    assert result.passed is False


def test_remote_cannot_override_sandbox_timeout():
    result = _eval(dict(passed=True, target_check_passed=True,
                        regression_free=True, policy_safe=True),
                   sandbox=_sandbox(timed_out=True))
    assert result.passed is False


def test_missing_remote_target_verdict_fails_closed():
    result = _eval(dict(passed=True, regression_free=True, policy_safe=True))
    assert result.passed is False
    assert result.target_check_passed is False

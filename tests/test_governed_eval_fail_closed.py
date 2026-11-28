"""Fail-closed evaluation boundary regression tests. No network or paid model calls."""

from __future__ import annotations

import hashlib

from ci_failure_orchestrator.governed.evaluation import EvalForgeAdapter
from ci_failure_orchestrator.governed.models import RepairProposal, SandboxResult


def _proposal(files: tuple[str, ...] = ("src/main.py",), patch: str = "") -> RepairProposal:
    return RepairProposal(
        proposal_id="p1",
        run_id="r1",
        files_affected=files,
        proposed_patch=patch,
        reasoning_summary="",
        expected_impact="",
        risk_classification="low",
        verification_plan=(),
        rollback="",
    )


def _sandbox(*, applied: bool = True, timed_out: bool = False) -> SandboxResult:
    return SandboxResult(
        run_id="r1",
        proposal_id="p1",
        applied=applied,
        commands_run=(),
        stdout_excerpt="",
        stderr_excerpt="",
        timed_out=timed_out,
    )


def _complete_remote(proposal: RepairProposal, **overrides: object) -> dict[str, object]:
    remote: dict[str, object] = {
        "run_id": "r1",
        "proposal_id": proposal.proposal_id,
        "proposal_sha256": hashlib.sha256(proposal.proposed_patch.encode("utf-8")).hexdigest(),
        "passed": True,
        "target_check_passed": True,
        "regression_free": True,
        "policy_safe": True,
        "evidence": ["remote fixture"],
    }
    remote.update(overrides)
    return remote


def _eval(remote: dict[str, object], *, proposal: RepairProposal | None = None, sandbox: SandboxResult | None = None, target: bool = True):
    adapter = EvalForgeAdapter(submit=lambda payload: "handle", fetch=lambda handle: remote)
    return adapter.evaluate(
        run_id="r1",
        proposal=proposal or _proposal(),
        sandbox=sandbox or _sandbox(),
        target_check_passed=target,
    )


def test_complete_remote_verdict_and_local_checks_pass():
    proposal = _proposal()
    result = _eval(_complete_remote(proposal), proposal=proposal)
    assert result.passed is True
    assert "remote fixture" in result.evidence


def test_missing_remote_policy_and_regression_fail_closed():
    proposal = _proposal()
    remote = _complete_remote(proposal)
    del remote["policy_safe"]
    del remote["regression_free"]
    result = _eval(remote, proposal=proposal)
    assert result.passed is False
    assert result.policy_safe is False
    assert result.regression_free is False


def test_remote_string_true_never_counts_as_boolean_approval():
    proposal = _proposal()
    result = _eval(_complete_remote(proposal, passed="true"), proposal=proposal)
    assert result.passed is False


def test_remote_cannot_override_failed_local_test():
    proposal = _proposal()
    result = _eval(_complete_remote(proposal), proposal=proposal, target=False)
    assert result.passed is False
    assert result.target_check_passed is False


def test_remote_cannot_override_sensitive_path_policy():
    proposal = _proposal((".github/workflows/deploy.yml",))
    result = _eval(_complete_remote(proposal), proposal=proposal)
    assert result.passed is False
    assert result.policy_safe is False


def test_remote_cannot_override_unapplied_sandbox():
    proposal = _proposal()
    result = _eval(_complete_remote(proposal), proposal=proposal, sandbox=_sandbox(applied=False))
    assert result.passed is False


def test_remote_cannot_override_sandbox_timeout():
    proposal = _proposal()
    result = _eval(_complete_remote(proposal), proposal=proposal, sandbox=_sandbox(timed_out=True))
    assert result.passed is False


def test_missing_remote_target_verdict_fails_closed():
    proposal = _proposal()
    remote = _complete_remote(proposal)
    del remote["target_check_passed"]
    result = _eval(remote, proposal=proposal)
    assert result.passed is False
    assert result.target_check_passed is False

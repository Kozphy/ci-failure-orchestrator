"""P0 strict external evaluation contract; all provider replies are synthetic."""

import hashlib
from dataclasses import replace

import pytest

from ci_failure_orchestrator.governed.evaluation import EvalForgeAdapter
from ci_failure_orchestrator.governed.models import RepairProposal, SandboxResult


@pytest.fixture
def inputs():
    return {
        "run_id": "synthetic-run",
        "proposal": RepairProposal(
            "proposal-1",
            "synthetic-run",
            ("src/a.py",),
            "synthetic patch",
            "reason",
            "impact",
            "low",
            ("pytest",),
            "revert",
        ),
        "sandbox": SandboxResult("synthetic-run", "proposal-1", True, (), "", ""),
        "target_check_passed": True,
    }


def response(inputs):
    return {
        "run_id": inputs["run_id"],
        "proposal_id": inputs["proposal"].proposal_id,
        "proposal_sha256": hashlib.sha256(inputs["proposal"].proposed_patch.encode()).hexdigest(),
        "passed": True,
        "target_check_passed": True,
        "regression_free": True,
        "policy_safe": True,
        "evidence": ["synthetic independent evaluator fixture"],
    }


def evaluate(inputs, reply):
    return EvalForgeAdapter(submit=lambda payload: "handle", fetch=lambda handle: reply).evaluate(**inputs)


def test_valid_response(inputs):
    assert evaluate(inputs, response(inputs)).passed is True


@pytest.mark.parametrize("field", ["passed", "target_check_passed", "regression_free", "policy_safe"])
@pytest.mark.parametrize("value", ["false", "true", None, 0, 1, [], {}])
def test_non_boolean_never_approves(inputs, field, value):
    reply = response(inputs)
    reply[field] = value
    result = evaluate(inputs, reply)
    assert not result.passed and not result.policy_safe


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "proposal_id",
        "proposal_sha256",
        "passed",
        "target_check_passed",
        "regression_free",
        "policy_safe",
        "evidence",
    ],
)
def test_missing_fields_fail_closed(inputs, field):
    reply = response(inputs)
    del reply[field]
    assert not evaluate(inputs, reply).passed


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "other"),
        ("proposal_id", "other"),
        ("proposal_sha256", "bad"),
        ("evidence", []),
        ("evidence", "not-list"),
        ("score", float("nan")),
        ("score", True),
        ("score", 1.1),
        ("regression_free", False),
        ("policy_safe", False),
        ("unknown", True),
    ],
)
def test_malformed_or_contradictory_response(inputs, field, value):
    reply = response(inputs)
    reply[field] = value
    assert not evaluate(inputs, reply).passed


def test_required_service_no_silent_local_fallback(inputs):
    assert not EvalForgeAdapter().evaluate(**inputs).passed
    local = EvalForgeAdapter(allow_local_fallback=True).evaluate(**inputs)
    assert local.passed
    assert "local_fallback_not_independent" in local.evidence


@pytest.mark.parametrize("exc", [TimeoutError("synthetic secret"), RuntimeError("synthetic secret")])
def test_provider_failure_is_redacted_block(inputs, exc):
    def fail(handle):
        raise exc

    result = EvalForgeAdapter(submit=lambda p: "handle", fetch=fail).evaluate(**inputs)
    assert not result.passed
    assert "synthetic secret" not in str(result.evidence)


@pytest.mark.parametrize("field,value", [("timed_out", True), ("applied", False), ("error", "failed")])
def test_remote_cannot_override_local_failure(inputs, field, value):
    inputs["sandbox"] = replace(inputs["sandbox"], **{field: value})
    assert not evaluate(inputs, response(inputs)).passed


def test_stale_local_identity_blocked_before_provider(inputs):
    inputs["sandbox"] = replace(inputs["sandbox"], run_id="other")

    def forbidden(payload):
        pytest.fail("provider called with stale identity")

    assert not EvalForgeAdapter(submit=forbidden, fetch=forbidden).evaluate(**inputs).passed

"""Negative and positive tests for the agent task scope gate."""

import pytest

from ci_failure_orchestrator.governed_agent import TaskContract, validate_changes


@pytest.fixture
def contract():
    return TaskContract(
        task_id="repair-001",
        allowed_paths=("ci_failure_orchestrator/doctor/**",),
        acceptance_commands=("python -m pytest -q",),
        max_attempts=3,
        max_changed_files=2,
    )


def test_authorized_change_is_in_scope(contract):
    decision = validate_changes(contract, ["ci_failure_orchestrator/doctor/diagnose.py"], attempt=1)
    assert decision.allowed
    assert decision.reasons == ()


@pytest.mark.parametrize("path", [
    "tests/test_example.py",
    ".github/workflows/ci.yml",
    "ci_failure_orchestrator/governed_agent/contract.py",
    "pyproject.toml",
])
def test_protected_paths_blocked_even_if_allowlisted(path):
    broad = TaskContract("task", ("**",), ("pytest",))
    decision = validate_changes(broad, [path], attempt=1)
    assert not decision.allowed
    assert any(reason.startswith("protected_path:") for reason in decision.reasons)


@pytest.mark.parametrize("path", [
    "../escape.py", "/tmp/escape.py", "a/../b.py", "a//b.py",
    "a\\b.py", "a/*.py", ".git/config",
])
def test_unsafe_or_protected_paths_fail_closed(contract, path):
    assert not validate_changes(contract, [path], attempt=1).allowed


def test_scope_violation_blocks(contract):
    decision = validate_changes(contract, ["ci_failure_orchestrator/other.py"], attempt=1)
    assert decision.reasons == ("outside_allowed_scope:ci_failure_orchestrator/other.py",)


def test_missing_diff_evidence_blocks(contract):
    assert "missing_diff_evidence" in validate_changes(contract, [], attempt=1).reasons


def test_attempt_budget_blocks(contract):
    assert "attempt_budget_exceeded" in validate_changes(
        contract, ["ci_failure_orchestrator/doctor/a.py"], attempt=4
    ).reasons


def test_file_budget_blocks(contract):
    paths = [f"ci_failure_orchestrator/doctor/{n}.py" for n in range(3)]
    assert "changed_file_budget_exceeded" in validate_changes(contract, paths, attempt=1).reasons


def test_duplicate_path_blocks(contract):
    path = "ci_failure_orchestrator/doctor/a.py"
    assert "duplicate_changed_paths" in validate_changes(contract, [path, path], attempt=1).reasons


@pytest.mark.parametrize("kwargs", [
    {"task_id": "", "allowed_paths": ("src/**",), "acceptance_commands": ("pytest",)},
    {"task_id": "a", "allowed_paths": ("../bad",), "acceptance_commands": ("pytest",)},
    {"task_id": "a", "allowed_paths": ("src/**",), "acceptance_commands": ()},
    {"task_id": "a", "allowed_paths": ("src/**",), "acceptance_commands": ("pytest",), "max_attempts": 0},
])
def test_invalid_contract_rejected(kwargs):
    with pytest.raises(ValueError):
        TaskContract(**kwargs)

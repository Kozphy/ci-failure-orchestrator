"""Phase 2–6 foundation unit and integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ci_failure_orchestrator.foundation import (
    AgentExecutionFoundation,
    FailureEvent,
    FoundationStateMachine,
    InvalidStateTransition,
    RunStatus,
)
from ci_failure_orchestrator.foundation.context import ContextBuilder
from ci_failure_orchestrator.foundation.evaluator import LocalEvaluator
from ci_failure_orchestrator.foundation.models import (
    CheckStatus,
    RepairProposal,
    SandboxResult,
    ToolResult,
    new_id,
)
from ci_failure_orchestrator.foundation.planner import DeterministicPlanner
from ci_failure_orchestrator.foundation.sanitization import REDACTED, sanitize_text
from ci_failure_orchestrator.foundation.state_machine import ALLOWED_TRANSITIONS
from ci_failure_orchestrator.foundation.tools import (
    ToolValidationError,
    build_default_registry,
)
from ci_failure_orchestrator.foundation.classifier import FailureClassifier
from ci_failure_orchestrator.foundation.sandbox import TempCopySandboxExecutor


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
    )
    base.update(kwargs)
    return FailureEvent(**base)


def test_models_serialize() -> None:
    event = _event()
    data = event.to_dict()
    assert data["schema_version"]
    assert FailureEvent.from_dict(data).run_id == event.run_id


def test_state_machine_valid_and_invalid() -> None:
    sm = FoundationStateMachine()
    sm.transition(RunStatus.CONTEXT_READY, "ok")
    sm.transition(RunStatus.CLASSIFIED, "ok")
    with pytest.raises(InvalidStateTransition):
        sm.transition(RunStatus.APPROVED, "nope")
    assert RunStatus.APPROVED not in ALLOWED_TRANSITIONS[RunStatus.CLASSIFIED]


def test_terminal_states_have_no_exits() -> None:
    assert ALLOWED_TRANSITIONS[RunStatus.APPROVED] == frozenset()
    assert ALLOWED_TRANSITIONS[RunStatus.REJECTED] == frozenset()
    assert ALLOWED_TRANSITIONS[RunStatus.ESCALATION_ERROR] == frozenset()
    assert ALLOWED_TRANSITIONS[RunStatus.FAILED] == frozenset()
    assert ALLOWED_TRANSITIONS[RunStatus.SUCCEEDED] == frozenset()
    # AWAITING_HUMAN is automation-terminal but allows explicit human decisions
    assert ALLOWED_TRANSITIONS[RunStatus.AWAITING_HUMAN] == frozenset(
        {RunStatus.APPROVED, RunStatus.REJECTED, RunStatus.FAILED}
    )


def test_sanitizer_redacts_secrets_preserves_code() -> None:
    text = "\n".join(
        [
            "Authorization: Bearer abcdefghijklmnop",
            "api_key = supersecretvalue",
            "password: hunter2",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "-----BEGIN PRIVATE KEY-----\nABC\n-----END PRIVATE KEY-----",
            "def add(a, b):\n    return a + b",
        ]
    )
    cleaned, count = sanitize_text(text)
    assert count >= 4
    assert "supersecretvalue" not in cleaned
    assert "hunter2" not in cleaned
    assert REDACTED in cleaned
    assert "def add(a, b):" in cleaned


def test_context_builder_prioritizes_and_truncates() -> None:
    event = _event(
        message="failed api_key=should_redact " + ("x" * 100),
        log_excerpt="password=nope\n" + ("L\n" * 5000),
        changed_paths=("src/a.py", "../evil.py"),
    )
    ctx = ContextBuilder().build(event)
    blob = "\n".join(ctx.prioritized_evidence)
    assert "failed_step:" in blob
    assert "message:" in blob
    assert "../evil.py" not in ",".join(ctx.changed_paths)
    assert "should_redact" not in blob
    assert ctx.redactions_applied >= 1


def test_planner_deterministic_and_tool_names_registered() -> None:
    event = _event()
    ctx = ContextBuilder().build(event)
    classification = FailureClassifier().classify(event)
    plan = DeterministicPlanner().plan(ctx, classification)
    registry = build_default_registry()
    names = {t.name for t in registry.list_tools()}
    for tool in plan.required_tools:
        assert tool in names
    assert plan.verification_steps


def test_tool_registry_duplicate_and_path_policy() -> None:
    registry = build_default_registry()
    with pytest.raises(ToolValidationError):
        registry.register(registry.get("log_reader"))
    _, result = registry.invoke("r", "file_reader", {"path": "../x"})
    assert result.success is False


def test_sandbox_applies_and_cleans_up(tmp_path: Path) -> None:
    src = tmp_path / "repo"
    src.mkdir()
    (src / "src").mkdir()
    (src / "src" / "app.py").write_text("x=1\n", encoding="utf-8")
    sandbox = TempCopySandboxExecutor(source_root=src)
    proposal = RepairProposal(
        proposal_id="p1",
        run_id="r1",
        files_changed=("src/app.py",),
        patch="--- a/src/app.py\n+++ b/src/app.py\n",
        rationale="fix",
        expected_effect="pass",
        verification_plan=("target_verification", "scope_check"),
    )
    result = sandbox.execute(proposal, proposal.verification_plan, target_should_pass=True)
    assert result.patch_applied is True
    assert result.success is True
    # Primary tree unchanged beyond original
    assert "foundation-patch" not in (src / "src" / "app.py").read_text(encoding="utf-8")


def test_sandbox_rejects_forbidden_path() -> None:
    sandbox = TempCopySandboxExecutor()
    proposal = RepairProposal(
        proposal_id="p2",
        run_id="r2",
        files_changed=("secrets/token",),
        patch="diff",
        rationale="bad",
        expected_effect="x",
        verification_plan=("target_verification",),
    )
    result = sandbox.execute(proposal, proposal.verification_plan)
    assert result.patch_applied is False
    assert result.error and "forbidden_path" in result.error


def test_evaluator_success_and_fail_paths() -> None:
    evaluator = LocalEvaluator()
    proposal = RepairProposal(
        proposal_id="p",
        run_id="r",
        files_changed=("src/a.py",),
        patch="diff",
        rationale="r",
        expected_effect="e",
        verification_plan=("target_verification",),
    )
    ok_sandbox = SandboxResult(
        run_id="r",
        proposal_id="p",
        success=True,
        patch_applied=True,
        command_results=(ToolResult("test_runner", True, 0, stdout="PASS"),),
        changed_files=("src/a.py",),
    )
    ok = evaluator.evaluate(proposal=proposal, sandbox=ok_sandbox)
    assert ok.passed is True
    assert ok.checks[0].status is CheckStatus.PASSED

    bad = evaluator.evaluate(
        proposal=proposal,
        sandbox=SandboxResult(
            run_id="r",
            proposal_id="p",
            success=False,
            patch_applied=True,
            command_results=(ToolResult("test_runner", False, 1, stdout="FAIL"),),
            changed_files=("src/a.py",),
        ),
    )
    assert bad.passed is False


def test_integration_simple_test_failure_passes() -> None:
    foundation = AgentExecutionFoundation()
    result = foundation.run(_event(run_id="int-pass", message="AssertionError: x"))
    # Phase 8: technical PASS + low-risk → APPROVED (SUCCEEDED was Phase 2–7 terminal)
    assert result.status is RunStatus.APPROVED
    assert result.technical_status == "PASS"
    assert result.run.evaluation is not None
    assert result.run.evaluation.passed is True
    assert result.run.proposal is not None


def test_integration_target_still_fails() -> None:
    foundation = AgentExecutionFoundation(force_target_fail=True)
    result = foundation.run(_event(run_id="int-fail"))
    assert result.status is RunStatus.FAILED
    assert result.technical_status == "FAIL"
    assert result.run.evaluation is not None
    assert result.run.evaluation.passed is False


def test_integration_forbidden_file_rejected() -> None:
    foundation = AgentExecutionFoundation(force_forbidden_path=True)
    result = foundation.run(_event(run_id="int-forbid", message="ruff check failed", job="lint", failed_step="ruff"))
    assert result.status is RunStatus.FAILED
    assert result.run.evaluation is not None
    assert (
        result.run.evaluation.forbidden_changes_detected
        or (result.run.sandbox and result.run.sandbox.error)
    )

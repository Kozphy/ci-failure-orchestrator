"""Tests for the governed agent pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from ci_failure_orchestrator.audit import HashChainedAuditLog
from ci_failure_orchestrator.governed import (
    FailureEvent,
    GovernedAgentPipeline,
    IllegalTransitionError,
    PipelineState,
    PipelineStateMachine,
    failure_event_from_dict,
)
from ci_failure_orchestrator.governed.benchmark_runner import run_benchmark_suite
from ci_failure_orchestrator.governed.context import ContextBuilder
from ci_failure_orchestrator.governed.models import new_id
from ci_failure_orchestrator.governed.policy import PolicyEngine
from ci_failure_orchestrator.governed.retry import RetryBudget
from ci_failure_orchestrator.governed.state_machine import ALLOWED_TRANSITIONS
from ci_failure_orchestrator.governed.store import SQLiteGovernedStore
from ci_failure_orchestrator.governed.tools import build_default_registry


def test_state_machine_rejects_illegal_transition() -> None:
    sm = PipelineStateMachine()
    with pytest.raises(IllegalTransitionError):
        sm.transition(PipelineState.SUCCEEDED, "nope")


def test_state_machine_allows_documented_edges() -> None:
    assert PipelineState.PLANNED in ALLOWED_TRANSITIONS[PipelineState.CLASSIFIED]


def test_context_builder_redacts_and_budgets() -> None:
    event = FailureEvent(
        event_id=new_id("evt"),
        run_id=new_id("run"),
        source="test",
        workflow="ci",
        job="test",
        failed_step="pytest",
        message="failed with api_key=supersecret and token=abc",
        changed_paths=("src/a.py", "../escape.py"),
        log_excerpt="password=hunter2\n" + ("x" * 10_000),
    )
    ctx = ContextBuilder().build(event)
    blob = "\n".join(ctx.prioritized_evidence)
    assert "supersecret" not in blob.lower() or "REDACTED" in blob
    assert "hunter2" not in blob
    assert ctx.token_estimate > 0


def test_tool_registry_blocks_path_traversal() -> None:
    registry = build_default_registry()
    _, result = registry.invoke("run-1", "file_read", {"path": "../secrets"})
    assert result.ok is False


def test_retry_budget_stops_on_identical_failures() -> None:
    budget = RetryBudget(max_attempts=5, repeated_failure_limit=2)
    budget.record_attempt(failure_fingerprint="same")
    budget.record_attempt(failure_fingerprint="same")
    decision = budget.decide(run_id="r", evaluation=None)
    assert decision.should_retry is False
    assert decision.reason == "repeated_identical_failure"


def test_pipeline_happy_path_lint(tmp_path: Path) -> None:
    store = SQLiteGovernedStore(tmp_path / "g.db")
    audit = HashChainedAuditLog(tmp_path / "audit.jsonl")
    pipeline = GovernedAgentPipeline(store=store, audit_log=audit, retry_budget=RetryBudget(max_attempts=2))
    event = FailureEvent(
        event_id="e1",
        run_id="run-lint",
        source="fixture",
        workflow="ci",
        job="lint",
        failed_step="ruff",
        message="ruff check failed",
        changed_paths=("src/ok.py",),
        log_excerpt="ruff F401",
    )
    result = pipeline.run(event)
    assert result.state in {PipelineState.SUCCEEDED, PipelineState.AWAITING_HUMAN}
    assert result.classification is not None
    assert result.classification.failure_class == "lint_failure"
    assert store.load_run("run-lint") is not None
    assert "FAILURE_CLASSIFIED" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_pipeline_escalates_unknown(tmp_path: Path) -> None:
    pipeline = GovernedAgentPipeline(
        store=SQLiteGovernedStore(tmp_path / "g.db"),
        retry_budget=RetryBudget(max_attempts=1),
    )
    result = pipeline.run(
        FailureEvent(
            event_id="e2",
            run_id="run-unk",
            source="fixture",
            workflow="ci",
            job="mystery",
            failed_step="x",
            message="baffling unrelated anomaly",
            changed_paths=("src/a.py",),
        )
    )
    assert result.state is PipelineState.AWAITING_HUMAN
    assert result.escalation is not None
    assert "review" in result.escalation.recommended_review_action.lower()


def test_pipeline_escalates_sensitive_workflow_path(tmp_path: Path) -> None:
    pipeline = GovernedAgentPipeline(
        store=SQLiteGovernedStore(tmp_path / "g.db"),
        retry_budget=RetryBudget(max_attempts=2),
    )
    result = pipeline.run(
        FailureEvent(
            event_id="e3",
            run_id="run-wf",
            source="fixture",
            workflow="ci",
            job="lint",
            failed_step="ruff",
            message="ruff check failed",
            changed_paths=(".github/workflows/ci.yml",),
            log_excerpt="ruff failed",
        )
    )
    assert result.state is not PipelineState.SUCCEEDED
    assert result.state in {PipelineState.AWAITING_HUMAN, PipelineState.FAILED}


def test_policy_engine_escalates_auth_paths() -> None:
    from ci_failure_orchestrator.governed.models import (
        EvaluationResult,
        FailureClassification,
        RepairProposal,
    )

    engine = PolicyEngine()
    decision = engine.evaluate(
        run_id="r",
        proposal=RepairProposal(
            proposal_id="p",
            run_id="r",
            files_affected=("src/auth/login.py",),
            proposed_patch="diff",
            reasoning_summary="fix",
            expected_impact="x",
            risk_classification="high",
            verification_plan=("t",),
            rollback="revert",
        ),
        classification=FailureClassification(
            run_id="r",
            failure_class="test_failure",
            confidence=0.9,
            evidence=("e",),
            uncertainty="heuristic",
            recommended_next_action="plan",
        ),
        evaluation=EvaluationResult(
            run_id="r",
            passed=True,
            target_check_passed=True,
            regression_free=True,
            policy_safe=True,
            evidence=("ok",),
        ),
    )
    assert decision.outcome.value == "ESCALATE"


def test_synthetic_benchmark_suite() -> None:
    root = Path(__file__).resolve().parents[1] / "benchmarks" / "cases"
    summary = run_benchmark_suite(root)
    assert summary["synthetic"] is True
    assert summary["total"] >= 8
    assert summary["failed"] == 0


def test_failure_event_from_dict_roundtrip() -> None:
    event = failure_event_from_dict(
        {
            "workflow": "ci",
            "job": "test",
            "failed_step": "pytest",
            "message": "AssertionError",
            "changed_paths": ["a.py"],
        }
    )
    assert event.workflow == "ci"
    assert event.changed_paths == ("a.py",)

from __future__ import annotations

from ci_failure_orchestrator.langgraph_adapters import (
    InMemoryDeadLetterSink,
    budgeted_ai_hook,
    classifier_diagnose_hook,
    draft_pr_gate_hook,
    instrument_hook,
    repair_plan_prompt,
    repair_plan_to_state,
)
from ci_failure_orchestrator.repair_planner import RepairPlan
from ci_failure_orchestrator.telemetry import MetricsRegistry
from ci_failure_orchestrator.verification import VerificationStep


def test_classifier_adapter_uses_existing_classifier() -> None:
    result = classifier_diagnose_hook(
        {"failure_message": "connection reset while downloading dependency"}
    )

    assert result["failure_class"] == "NETWORK_ERROR"
    assert result["confidence"] == 0.9
    assert result["retryable"] is True


def test_budgeted_ai_hook_reports_usage_deltas() -> None:
    hook = budgeted_ai_hook(
        lambda state: {"patch": "candidate"},
        estimated_cost_usd=0.12,
    )

    result = hook({})

    assert result["patch"] == "candidate"
    assert result["ai_calls_delta"] == 1
    assert result["ai_cost_usd_delta"] == 0.12


def test_instrument_hook_records_runs_and_success() -> None:
    registry = MetricsRegistry()
    hook = instrument_hook("diagnose", lambda state: {"ok": True}, registry)

    assert hook({}) == {"ok": True}
    assert registry.counters["langgraph.node.diagnose.runs"] == 1
    assert registry.counters["langgraph.node.diagnose.success"] == 1
    assert len(registry.observations["langgraph.node.diagnose.latency_ms"]) == 1


def test_dead_letter_sink_captures_governance_context() -> None:
    sink = InMemoryDeadLetterSink()
    sink.hook(
        {
            "run_id": "run-1",
            "repository": "Kozphy/example",
            "failure_class": "NETWORK_ERROR",
            "retry_count": 2,
            "ai_calls": 4,
            "ai_cost_usd": 0.44,
            "reason": "budget exhausted",
        }
    )

    assert sink.records == [
        {
            "run_id": "run-1",
            "repository": "Kozphy/example",
            "failure_class": "NETWORK_ERROR",
            "retry_count": 2,
            "ai_calls": 4,
            "ai_cost_usd": 0.44,
            "reason": "budget exhausted",
        }
    ]


def _sample_plan(*, approval: bool = False) -> RepairPlan:
    return RepairPlan(
        root_stage="test",
        hypothesis="TEST_ASSERTION at test is the leading root-cause hypothesis",
        target_files=("src/example.py",),
        proposed_change="repair the smallest failing assertion path",
        verification=(
            VerificationStep("test", "targeted", "verify root fix"),
            VerificationStep("*", "full-pipeline", "guard regressions"),
        ),
        risk="high" if approval else "medium",
        requires_human_approval=approval,
    )


def test_repair_plan_prompt_uses_formal_plan_contract() -> None:
    plan = _sample_plan()
    prompt = repair_plan_prompt(plan, {"failure_message": "expected 2 got 3"})

    assert "Root stage: test" in prompt
    assert "Target files: src/example.py" in prompt
    assert "Required verification: test:targeted, *:full-pipeline" in prompt
    assert "Failure message: expected 2 got 3" in prompt
    assert "Do not weaken tests" in prompt


def test_repair_plan_state_preserves_approval_boundary() -> None:
    update = repair_plan_to_state(_sample_plan(approval=True))

    assert update["repair_risk"] == "high"
    assert update["repair_requires_human_approval"] is True


def test_draft_pr_gate_blocks_unapproved_high_risk_plan() -> None:
    state = {
        "sandbox_passed": True,
        "regression_free": True,
        "verification_score": 1.0,
        "repair_requires_human_approval": True,
        "human_approved": False,
    }

    result = draft_pr_gate_hook(state)

    assert result["draft_pr_allowed"] is False
    assert "repair_plan_requires_human_approval" in result["delivery_gate_reasons"]


def test_draft_pr_gate_allows_approved_high_risk_plan() -> None:
    state = {
        "sandbox_passed": True,
        "regression_free": True,
        "verification_score": 1.0,
        "repair_requires_human_approval": True,
        "human_approved": True,
    }

    result = draft_pr_gate_hook(state)

    assert result["draft_pr_allowed"] is True
    assert result["delivery_gate_reasons"] == []

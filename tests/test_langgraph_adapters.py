from __future__ import annotations

from ci_failure_orchestrator.langgraph_adapters import (
    InMemoryDeadLetterSink,
    budgeted_ai_hook,
    classifier_diagnose_hook,
    instrument_hook,
)
from ci_failure_orchestrator.telemetry import MetricsRegistry


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

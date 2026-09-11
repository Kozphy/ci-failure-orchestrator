from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .classifier import classify_error
from .langgraph_runtime import AgentWorkflowState, StateHook, StateUpdate
from .telemetry import MetricsRegistry, Timer


RETRYABLE_FAILURE_CLASSES = frozenset(
    {
        "NETWORK_ERROR",
        "FLAKY_TEST",
        "PACKAGE_ERROR",
        "RUNTIME_ERROR",
    }
)


def classifier_diagnose_hook(state: AgentWorkflowState) -> StateUpdate:
    """Adapt the repository's existing deterministic classifier to LangGraph state."""

    message = state.get("failure_message", "")
    failure_class, confidence = classify_error(message)
    return {
        "failure_class": failure_class,
        "confidence": confidence,
        "retryable": failure_class in RETRYABLE_FAILURE_CLASSES,
        "diagnosis": f"deterministic classifier selected {failure_class}",
    }


def instrument_hook(
    name: str,
    hook: StateHook,
    registry: MetricsRegistry,
) -> StateHook:
    """Wrap a graph hook with the repository's dependency-free telemetry registry."""

    metric = f"langgraph.node.{name}.latency_ms"

    def wrapped(state: AgentWorkflowState) -> StateUpdate:
        registry.inc(f"langgraph.node.{name}.runs")
        with Timer(registry, metric):
            try:
                update = hook(state)
            except Exception:
                registry.inc(f"langgraph.node.{name}.errors")
                raise
        registry.inc(f"langgraph.node.{name}.success")
        return update

    return wrapped


@dataclass
class InMemoryDeadLetterSink:
    """Test/local dead-letter sink; production callers can inject a durable sink hook."""

    records: list[dict[str, Any]] = field(default_factory=list)

    def hook(self, state: AgentWorkflowState) -> StateUpdate:
        record = {
            "run_id": state.get("run_id"),
            "repository": state.get("repository"),
            "failure_class": state.get("failure_class"),
            "retry_count": int(state.get("retry_count", 0)),
            "ai_calls": int(state.get("ai_calls", 0)),
            "ai_cost_usd": float(state.get("ai_cost_usd", 0.0)),
            "reason": state.get("dead_letter_reason") or state.get("reason"),
        }
        self.records.append(record)
        return {"dead_letter_reason": str(record["reason"] or "dead-lettered")}


def budgeted_ai_hook(
    hook: StateHook,
    *,
    estimated_cost_usd: float,
    calls: int = 1,
) -> StateHook:
    """Annotate an AI-backed hook with usage deltas consumed by the graph runtime.

    The wrapper intentionally does not enforce the budget itself. Enforcement lives in
    the orchestration layer so all AI providers share one durable budget ledger.
    """

    if calls < 0 or estimated_cost_usd < 0:
        raise ValueError("AI usage estimates must be non-negative")

    def wrapped(state: AgentWorkflowState) -> StateUpdate:
        update = dict(hook(state))
        update["ai_calls_delta"] = calls
        update["ai_cost_usd_delta"] = estimated_cost_usd
        return update

    return wrapped


def compose_hooks(*hooks: Callable[[AgentWorkflowState], StateUpdate]) -> StateHook:
    """Compose small state hooks without hiding later updates behind framework magic."""

    def composed(state: AgentWorkflowState) -> StateUpdate:
        current: dict[str, Any] = dict(state)
        merged: StateUpdate = {}
        for hook in hooks:
            update = hook(current)
            merged.update(update)
            current.update(update)
        return merged

    return composed

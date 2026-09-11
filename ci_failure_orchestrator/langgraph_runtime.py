from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypedDict

from .policy import Action, PolicyContext, PolicyEngine


class AgentWorkflowState(TypedDict, total=False):
    """Serializable state shared by the optional LangGraph control-plane adapter."""

    run_id: str
    repository: str
    failure_message: str
    failure_class: str
    confidence: float
    retryable: bool
    retry_count: int
    retry_budget: int
    repeated_signature: int
    ct_regression: bool
    security_severity: str | None
    canary_regression: bool
    diagnosis: str
    patch: str
    sandbox_passed: bool
    verification_score: float
    regression_free: bool
    human_approved: bool
    action: str
    reason: str
    audit_events: list[str]
    ai_calls: int
    ai_cost_usd: float
    max_ai_calls: int
    max_ai_cost_usd: float
    budget_exhausted: bool
    dead_lettered: bool
    dead_letter_reason: str


StateUpdate = dict[str, Any]
StateHook = Callable[[AgentWorkflowState], StateUpdate]


@dataclass(frozen=True)
class LangGraphHooks:
    """Dependency-inversion boundary between orchestration and repair implementation.

    The existing deterministic components remain the source of truth. LangGraph only
    coordinates them, which keeps the repository usable without the optional
    ``langgraph`` dependency and avoids framework lock-in.

    Hooks that invoke an AI provider may report ``ai_calls_delta`` and
    ``ai_cost_usd_delta`` in their returned update. The runtime folds those deltas
    into durable state and applies the configured fail-closed budget before another
    autonomous repair attempt is allowed.
    """

    diagnose: StateHook
    generate_patch: StateHook
    sandbox: StateHook
    verify: StateHook
    rollback: StateHook
    audit: StateHook
    approve: StateHook | None = None
    dead_letter: StateHook | None = None


def _append_event(state: AgentWorkflowState, event: str) -> list[str]:
    return [*state.get("audit_events", []), event]


def _budget_exhausted(state: AgentWorkflowState) -> bool:
    calls = int(state.get("ai_calls", 0))
    cost = float(state.get("ai_cost_usd", 0.0))
    max_calls = int(state.get("max_ai_calls", 8))
    max_cost = float(state.get("max_ai_cost_usd", 1.0))
    return calls >= max_calls or cost >= max_cost


def _apply_usage(state: AgentWorkflowState, update: StateUpdate) -> StateUpdate:
    """Fold hook-reported AI usage deltas into durable workflow state."""

    result = dict(update)
    calls_delta = int(result.pop("ai_calls_delta", 0))
    cost_delta = float(result.pop("ai_cost_usd_delta", 0.0))
    calls = int(state.get("ai_calls", 0)) + calls_delta
    cost = float(state.get("ai_cost_usd", 0.0)) + cost_delta
    max_calls = int(state.get("max_ai_calls", 8))
    max_cost = float(state.get("max_ai_cost_usd", 1.0))
    result["ai_calls"] = calls
    result["ai_cost_usd"] = cost
    result["budget_exhausted"] = calls >= max_calls or cost >= max_cost
    return result


def _policy_node(state: AgentWorkflowState) -> StateUpdate:
    decision = PolicyEngine().decide(
        PolicyContext(
            failure_class=state.get("failure_class", "unknown"),
            confidence=float(state.get("confidence", 0.0)),
            retryable=bool(state.get("retryable", False)),
            retry_count=int(state.get("retry_count", 0)),
            retry_budget=int(state.get("retry_budget", 2)),
            repeated_signature=int(state.get("repeated_signature", 0)),
            ct_regression=bool(state.get("ct_regression", False)),
            security_severity=state.get("security_severity"),
            canary_regression=bool(state.get("canary_regression", False)),
        )
    )
    return {
        "action": decision.action.value,
        "reason": decision.reason,
        "audit_events": _append_event(state, f"policy:{decision.action.value}"),
    }


def _route_policy(state: AgentWorkflowState) -> str:
    if bool(state.get("budget_exhausted")) or _budget_exhausted(state):
        return "dead_letter"
    action = state.get("action", Action.ESCALATE.value)
    if action == Action.RETRY.value:
        return "generate_patch"
    if action == Action.ROLLBACK.value:
        return "rollback"
    if action == Action.ESCALATE.value:
        return "approval"
    return "audit"


def _route_verification(state: AgentWorkflowState) -> str:
    if bool(state.get("sandbox_passed")) and bool(state.get("regression_free")):
        if float(state.get("verification_score", 0.0)) >= 0.80:
            return "audit"

    if not bool(state.get("regression_free", True)):
        return "rollback"

    if bool(state.get("budget_exhausted")) or _budget_exhausted(state):
        return "dead_letter"

    if int(state.get("retry_count", 0)) < int(state.get("retry_budget", 2)):
        return "retry"
    return "approval"


def _route_approval(state: AgentWorkflowState) -> str:
    if not bool(state.get("human_approved")):
        return "audit"
    if bool(state.get("budget_exhausted")) or _budget_exhausted(state):
        return "dead_letter"
    return "generate_patch"


def build_control_plane_graph(
    hooks: LangGraphHooks,
    *,
    checkpointer: Any | None = None,
):
    """Build an optional LangGraph workflow over the deterministic repair core.

    LangGraph is imported lazily so the base package has no mandatory agent-framework
    dependency. Install with ``pip install -e '.[langgraph]'`` to enable this adapter.
    """

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "LangGraph support is optional. Install with: pip install -e '.[langgraph]'"
        ) from exc

    def run_hook(name: str, hook: StateHook, state: AgentWorkflowState) -> StateUpdate:
        update = _apply_usage(state, hook(state))
        update["audit_events"] = _append_event(state, name)
        return update

    def diagnose(state: AgentWorkflowState) -> StateUpdate:
        return run_hook("diagnose", hooks.diagnose, state)

    def generate_patch(state: AgentWorkflowState) -> StateUpdate:
        return run_hook("generate_patch", hooks.generate_patch, state)

    def sandbox(state: AgentWorkflowState) -> StateUpdate:
        return run_hook("sandbox", hooks.sandbox, state)

    def verify(state: AgentWorkflowState) -> StateUpdate:
        return run_hook("verify", hooks.verify, state)

    def retry(state: AgentWorkflowState) -> StateUpdate:
        return {
            "retry_count": int(state.get("retry_count", 0)) + 1,
            "audit_events": _append_event(state, "retry"),
        }

    def rollback(state: AgentWorkflowState) -> StateUpdate:
        update = run_hook("rollback", hooks.rollback, state)
        update["action"] = Action.ROLLBACK.value
        return update

    def approval(state: AgentWorkflowState) -> StateUpdate:
        if hooks.approve is not None:
            update = _apply_usage(state, hooks.approve(state))
        else:
            try:
                from langgraph.types import interrupt
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("Installed LangGraph version does not support interrupts") from exc
            approved = bool(
                interrupt(
                    {
                        "kind": "human_approval",
                        "run_id": state.get("run_id"),
                        "reason": state.get("reason", "policy escalation"),
                        "ai_calls": int(state.get("ai_calls", 0)),
                        "ai_cost_usd": float(state.get("ai_cost_usd", 0.0)),
                    }
                )
            )
            update = {"human_approved": approved}
        update["audit_events"] = _append_event(state, "approval")
        return update

    def dead_letter(state: AgentWorkflowState) -> StateUpdate:
        reason = state.get("dead_letter_reason") or "AI invocation budget exhausted"
        if hooks.dead_letter is not None:
            update = _apply_usage(state, hooks.dead_letter(state))
        else:
            update = {}
        update.update(
            {
                "action": Action.ESCALATE.value,
                "dead_lettered": True,
                "dead_letter_reason": reason,
                "reason": reason,
                "audit_events": _append_event(state, "dead_letter"),
            }
        )
        return update

    def audit(state: AgentWorkflowState) -> StateUpdate:
        return run_hook("audit", hooks.audit, state)

    graph = StateGraph(AgentWorkflowState)
    graph.add_node("diagnose", diagnose)
    graph.add_node("policy", _policy_node)
    graph.add_node("generate_patch", generate_patch)
    graph.add_node("sandbox", sandbox)
    graph.add_node("verify", verify)
    graph.add_node("retry", retry)
    graph.add_node("rollback", rollback)
    graph.add_node("approval", approval)
    graph.add_node("dead_letter", dead_letter)
    graph.add_node("audit", audit)

    graph.add_edge(START, "diagnose")
    graph.add_edge("diagnose", "policy")
    graph.add_conditional_edges(
        "policy",
        _route_policy,
        {
            "generate_patch": "generate_patch",
            "rollback": "rollback",
            "approval": "approval",
            "dead_letter": "dead_letter",
            "audit": "audit",
        },
    )
    graph.add_edge("generate_patch", "sandbox")
    graph.add_edge("sandbox", "verify")
    graph.add_conditional_edges(
        "verify",
        _route_verification,
        {
            "audit": "audit",
            "rollback": "rollback",
            "retry": "retry",
            "approval": "approval",
            "dead_letter": "dead_letter",
        },
    )
    graph.add_edge("retry", "diagnose")
    graph.add_conditional_edges(
        "approval",
        _route_approval,
        {
            "generate_patch": "generate_patch",
            "dead_letter": "dead_letter",
            "audit": "audit",
        },
    )
    graph.add_edge("rollback", "audit")
    graph.add_edge("dead_letter", "audit")
    graph.add_edge("audit", END)

    return graph.compile(checkpointer=checkpointer)

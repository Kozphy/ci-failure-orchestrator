from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypedDict

from .policy import Action, PolicyContext, PolicyEngine


class AgentWorkflowState(TypedDict, total=False):
    """Serializable state shared by the optional LangGraph control-plane adapter."""

    run_id: str
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


StateUpdate = dict[str, Any]
StateHook = Callable[[AgentWorkflowState], StateUpdate]


@dataclass(frozen=True)
class LangGraphHooks:
    """Dependency-inversion boundary between orchestration and repair implementation.

    The existing deterministic components remain the source of truth. LangGraph only
    coordinates them, which keeps the repository usable without the optional
    ``langgraph`` dependency and avoids framework lock-in.
    """

    diagnose: StateHook
    generate_patch: StateHook
    sandbox: StateHook
    verify: StateHook
    rollback: StateHook
    audit: StateHook
    approve: StateHook | None = None


def _append_event(state: AgentWorkflowState, event: str) -> list[str]:
    return [*state.get("audit_events", []), event]


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

    if int(state.get("retry_count", 0)) < int(state.get("retry_budget", 2)):
        return "retry"
    return "approval"


def _route_approval(state: AgentWorkflowState) -> str:
    return "generate_patch" if bool(state.get("human_approved")) else "audit"


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

    def diagnose(state: AgentWorkflowState) -> StateUpdate:
        update = hooks.diagnose(state)
        update["audit_events"] = _append_event(state, "diagnose")
        return update

    def generate_patch(state: AgentWorkflowState) -> StateUpdate:
        update = hooks.generate_patch(state)
        update["audit_events"] = _append_event(state, "generate_patch")
        return update

    def sandbox(state: AgentWorkflowState) -> StateUpdate:
        update = hooks.sandbox(state)
        update["audit_events"] = _append_event(state, "sandbox")
        return update

    def verify(state: AgentWorkflowState) -> StateUpdate:
        update = hooks.verify(state)
        update["audit_events"] = _append_event(state, "verify")
        return update

    def retry(state: AgentWorkflowState) -> StateUpdate:
        return {
            "retry_count": int(state.get("retry_count", 0)) + 1,
            "audit_events": _append_event(state, "retry"),
        }

    def rollback(state: AgentWorkflowState) -> StateUpdate:
        update = hooks.rollback(state)
        update["action"] = Action.ROLLBACK.value
        update["audit_events"] = _append_event(state, "rollback")
        return update

    def approval(state: AgentWorkflowState) -> StateUpdate:
        if hooks.approve is not None:
            update = hooks.approve(state)
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
                    }
                )
            )
            update = {"human_approved": approved}
        update["audit_events"] = _append_event(state, "approval")
        return update

    def audit(state: AgentWorkflowState) -> StateUpdate:
        update = hooks.audit(state)
        update["audit_events"] = _append_event(state, "audit")
        return update

    graph = StateGraph(AgentWorkflowState)
    graph.add_node("diagnose", diagnose)
    graph.add_node("policy", _policy_node)
    graph.add_node("generate_patch", generate_patch)
    graph.add_node("sandbox", sandbox)
    graph.add_node("verify", verify)
    graph.add_node("retry", retry)
    graph.add_node("rollback", rollback)
    graph.add_node("approval", approval)
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
        },
    )
    graph.add_edge("retry", "diagnose")
    graph.add_conditional_edges(
        "approval",
        _route_approval,
        {"generate_patch": "generate_patch", "audit": "audit"},
    )
    graph.add_edge("rollback", "audit")
    graph.add_edge("audit", END)

    return graph.compile(checkpointer=checkpointer)

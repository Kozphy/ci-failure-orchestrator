from __future__ import annotations

import pytest

from ci_failure_orchestrator.langgraph_runtime import LangGraphHooks, build_control_plane_graph


pytest.importorskip("langgraph")


def test_langgraph_happy_path_reaches_audit() -> None:
    hooks = LangGraphHooks(
        diagnose=lambda state: {
            "failure_class": "flaky_test",
            "confidence": 0.95,
            "retryable": True,
        },
        generate_patch=lambda state: {"patch": "candidate"},
        sandbox=lambda state: {"sandbox_passed": True},
        verify=lambda state: {
            "verification_score": 0.97,
            "regression_free": True,
        },
        rollback=lambda state: {"reason": "rolled back"},
        audit=lambda state: {"action": "PASS"},
        approve=lambda state: {"human_approved": False},
    )

    graph = build_control_plane_graph(hooks)
    result = graph.invoke(
        {
            "run_id": "test-run",
            "retry_count": 0,
            "retry_budget": 2,
            "audit_events": [],
        }
    )

    assert result["action"] == "PASS"
    assert result["sandbox_passed"] is True
    assert result["regression_free"] is True
    assert result["audit_events"] == [
        "diagnose",
        "policy:RETRY",
        "generate_patch",
        "sandbox",
        "verify",
        "audit",
    ]


def test_langgraph_regression_routes_to_rollback() -> None:
    hooks = LangGraphHooks(
        diagnose=lambda state: {
            "failure_class": "flaky_test",
            "confidence": 0.90,
            "retryable": True,
        },
        generate_patch=lambda state: {"patch": "candidate"},
        sandbox=lambda state: {"sandbox_passed": True},
        verify=lambda state: {
            "verification_score": 0.10,
            "regression_free": False,
        },
        rollback=lambda state: {"reason": "regression rollback"},
        audit=lambda state: {},
        approve=lambda state: {"human_approved": False},
    )

    graph = build_control_plane_graph(hooks)
    result = graph.invoke(
        {
            "run_id": "test-regression",
            "retry_count": 0,
            "retry_budget": 2,
            "audit_events": [],
        }
    )

    assert result["action"] == "ROLLBACK"
    assert "rollback" in result["audit_events"]
    assert result["audit_events"][-1] == "audit"


def test_langgraph_low_confidence_escalates_to_approval() -> None:
    hooks = LangGraphHooks(
        diagnose=lambda state: {
            "failure_class": "unknown",
            "confidence": 0.20,
            "retryable": True,
        },
        generate_patch=lambda state: {"patch": "should-not-run"},
        sandbox=lambda state: {"sandbox_passed": False},
        verify=lambda state: {
            "verification_score": 0.0,
            "regression_free": True,
        },
        rollback=lambda state: {},
        audit=lambda state: {},
        approve=lambda state: {"human_approved": False},
    )

    graph = build_control_plane_graph(hooks)
    result = graph.invoke(
        {
            "run_id": "test-escalation",
            "retry_count": 0,
            "retry_budget": 2,
            "audit_events": [],
        }
    )

    assert result["action"] == "ESCALATE"
    assert "approval" in result["audit_events"]
    assert "generate_patch" not in result["audit_events"]

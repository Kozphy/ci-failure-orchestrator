import pytest

from ci_failure_orchestrator.policy import Action, PolicyContext, PolicyEngine
from ci_failure_orchestrator.state_machine import DeliveryStateMachine, InvalidTransition, PipelineState


def test_policy_retries_flaky_failure_with_budget():
    decision = PolicyEngine().decide(PolicyContext("FLAKY", 0.9, True, retry_count=0, retry_budget=2))
    assert decision.action == Action.RETRY
    assert decision.retry_budget_remaining == 2


def test_policy_blocks_ct_regression():
    decision = PolicyEngine().decide(PolicyContext("CODE", 0.95, False, ct_regression=True))
    assert decision.action == Action.BLOCK


def test_policy_rolls_back_canary_regression():
    decision = PolicyEngine().decide(PolicyContext("DEPLOYMENT", 0.99, False, canary_regression=True))
    assert decision.action == Action.ROLLBACK


def test_policy_escalates_repeated_retryable_signature():
    decision = PolicyEngine().decide(PolicyContext("INFRASTRUCTURE", 0.8, True, repeated_signature=2))
    assert decision.action == Action.ESCALATE


def test_delivery_state_machine_happy_path():
    sm = DeliveryStateMachine()
    for state in (
        PipelineState.CI_RUNNING,
        PipelineState.CT_RUNNING,
        PipelineState.POLICY_REVIEW,
        PipelineState.READY_FOR_STAGING,
        PipelineState.STAGING,
        PipelineState.CANARY,
        PipelineState.RELEASED,
    ):
        sm.transition(state)
    assert sm.state == PipelineState.RELEASED


def test_invalid_transition_is_rejected():
    sm = DeliveryStateMachine()
    with pytest.raises(InvalidTransition):
        sm.transition(PipelineState.RELEASED)

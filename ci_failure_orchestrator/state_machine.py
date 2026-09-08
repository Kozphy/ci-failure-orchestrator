from __future__ import annotations

from enum import Enum


class PipelineState(str, Enum):
    RECEIVED = "received"
    CI_RUNNING = "ci_running"
    CI_FAILED = "ci_failed"
    DIAGNOSING = "diagnosing"
    VERIFYING = "verifying"
    CT_RUNNING = "ct_running"
    POLICY_REVIEW = "policy_review"
    READY_FOR_STAGING = "ready_for_staging"
    STAGING = "staging"
    CANARY = "canary"
    RELEASED = "released"
    RETRY_PENDING = "retry_pending"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    ROLLING_BACK = "rolling_back"


_ALLOWED = {
    PipelineState.RECEIVED: {PipelineState.CI_RUNNING},
    PipelineState.CI_RUNNING: {PipelineState.CI_FAILED, PipelineState.CT_RUNNING},
    PipelineState.CI_FAILED: {PipelineState.DIAGNOSING},
    PipelineState.DIAGNOSING: {PipelineState.VERIFYING, PipelineState.POLICY_REVIEW},
    PipelineState.VERIFYING: {PipelineState.CT_RUNNING, PipelineState.POLICY_REVIEW},
    PipelineState.CT_RUNNING: {PipelineState.POLICY_REVIEW},
    PipelineState.POLICY_REVIEW: {PipelineState.READY_FOR_STAGING, PipelineState.RETRY_PENDING, PipelineState.BLOCKED, PipelineState.ESCALATED, PipelineState.ROLLING_BACK},
    PipelineState.RETRY_PENDING: {PipelineState.CI_RUNNING, PipelineState.ESCALATED},
    PipelineState.READY_FOR_STAGING: {PipelineState.STAGING},
    PipelineState.STAGING: {PipelineState.CANARY, PipelineState.ROLLING_BACK, PipelineState.BLOCKED},
    PipelineState.CANARY: {PipelineState.RELEASED, PipelineState.ROLLING_BACK},
}


class InvalidTransition(ValueError):
    pass


class DeliveryStateMachine:
    def __init__(self, state: PipelineState = PipelineState.RECEIVED):
        self.state = state
        self.history = [state]

    def transition(self, target: PipelineState) -> PipelineState:
        if target not in _ALLOWED.get(self.state, set()):
            raise InvalidTransition(f"invalid transition: {self.state.value} -> {target.value}")
        self.state = target
        self.history.append(target)
        return self.state

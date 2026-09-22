"""Explicit lifecycle state machine for the governed pipeline."""

from __future__ import annotations

from .models import PipelineState

ALLOWED_TRANSITIONS: dict[PipelineState, frozenset[PipelineState]] = {
    PipelineState.RECEIVED: frozenset({PipelineState.CONTEXT_READY, PipelineState.CANCELLED}),
    PipelineState.CONTEXT_READY: frozenset({PipelineState.CLASSIFIED, PipelineState.FAILED}),
    PipelineState.CLASSIFIED: frozenset({PipelineState.PLANNED, PipelineState.AWAITING_HUMAN, PipelineState.FAILED}),
    PipelineState.PLANNED: frozenset({PipelineState.EXECUTING, PipelineState.FAILED}),
    PipelineState.EXECUTING: frozenset({PipelineState.EVALUATING, PipelineState.FAILED}),
    PipelineState.EVALUATING: frozenset(
        {
            PipelineState.POLICY_REVIEW,
            PipelineState.RETRYING,
            PipelineState.AWAITING_HUMAN,
            PipelineState.FAILED,
        }
    ),
    PipelineState.RETRYING: frozenset({PipelineState.PLANNED, PipelineState.AWAITING_HUMAN, PipelineState.FAILED}),
    PipelineState.POLICY_REVIEW: frozenset(
        {
            PipelineState.APPROVED,
            PipelineState.AWAITING_HUMAN,
            PipelineState.RETRYING,
            PipelineState.FAILED,
        }
    ),
    PipelineState.AWAITING_HUMAN: frozenset(
        {PipelineState.APPROVED, PipelineState.FAILED, PipelineState.CANCELLED}
    ),
    PipelineState.APPROVED: frozenset({PipelineState.APPLYING, PipelineState.VERIFYING}),
    PipelineState.APPLYING: frozenset({PipelineState.VERIFYING, PipelineState.FAILED}),
    PipelineState.VERIFYING: frozenset({PipelineState.SUCCEEDED, PipelineState.FAILED}),
    PipelineState.SUCCEEDED: frozenset(),
    PipelineState.FAILED: frozenset(),
    PipelineState.CANCELLED: frozenset(),
}


class IllegalTransitionError(ValueError):
    """Raised when a pipeline transition is not allowed."""


class PipelineStateMachine:
    def __init__(self, initial: PipelineState = PipelineState.RECEIVED) -> None:
        self.state = initial
        self.history: list[tuple[PipelineState, PipelineState, str]] = []

    def transition(self, to_state: PipelineState, reason: str) -> PipelineState:
        allowed = ALLOWED_TRANSITIONS[self.state]
        if to_state not in allowed:
            raise IllegalTransitionError(
                f"illegal transition {self.state.value} -> {to_state.value}: {reason}"
            )
        self.history.append((self.state, to_state, reason))
        self.state = to_state
        return self.state

    @property
    def terminal(self) -> bool:
        return self.state in {
            PipelineState.SUCCEEDED,
            PipelineState.FAILED,
            PipelineState.CANCELLED,
        }

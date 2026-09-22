"""Foundation state machine (Phases 2–9)."""

from __future__ import annotations

from .models import RunStatus

ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.RECEIVED: frozenset({RunStatus.CONTEXT_READY, RunStatus.FAILED}),
    RunStatus.CONTEXT_READY: frozenset({RunStatus.CLASSIFIED, RunStatus.FAILED}),
    RunStatus.CLASSIFIED: frozenset({RunStatus.PLANNED, RunStatus.FAILED}),
    RunStatus.PLANNED: frozenset({RunStatus.EXECUTING, RunStatus.FAILED}),
    RunStatus.EXECUTING: frozenset({RunStatus.PROPOSAL_READY, RunStatus.FAILED}),
    RunStatus.PROPOSAL_READY: frozenset({RunStatus.SANDBOX_RUNNING, RunStatus.FAILED}),
    RunStatus.SANDBOX_RUNNING: frozenset({RunStatus.EVALUATING, RunStatus.FAILED}),
    RunStatus.EVALUATING: frozenset({RunStatus.EVALUATED, RunStatus.FAILED}),
    RunStatus.EVALUATED: frozenset(
        {RunStatus.POLICY_REVIEW, RunStatus.RETRY_DECISION, RunStatus.FAILED}
    ),
    RunStatus.RETRY_DECISION: frozenset({RunStatus.RETRYING, RunStatus.FAILED}),
    RunStatus.RETRYING: frozenset({RunStatus.PLANNED, RunStatus.FAILED}),
    RunStatus.POLICY_REVIEW: frozenset(
        {
            RunStatus.APPROVED,
            RunStatus.REJECTED,
            RunStatus.ESCALATED,
            RunStatus.FAILED,
        }
    ),
    RunStatus.ESCALATED: frozenset(
        {RunStatus.ESCALATION_BUILDING, RunStatus.ESCALATION_ERROR, RunStatus.FAILED}
    ),
    RunStatus.ESCALATION_BUILDING: frozenset(
        {RunStatus.AWAITING_HUMAN, RunStatus.ESCALATION_ERROR, RunStatus.FAILED}
    ),
    RunStatus.APPROVED: frozenset(),
    RunStatus.REJECTED: frozenset(),
    RunStatus.AWAITING_HUMAN: frozenset(),
    RunStatus.ESCALATION_ERROR: frozenset(),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
}


class InvalidStateTransition(ValueError):
    """Raised when a foundation transition is illegal."""


class FoundationStateMachine:
    def __init__(self, initial: RunStatus = RunStatus.RECEIVED) -> None:
        self.status = initial
        self.history: list[tuple[RunStatus, RunStatus, str]] = []

    def transition(self, to_status: RunStatus, reason: str) -> RunStatus:
        allowed = ALLOWED_TRANSITIONS[self.status]
        if to_status not in allowed:
            raise InvalidStateTransition(
                f"illegal transition {self.status.value} -> {to_status.value}: {reason}"
            )
        self.history.append((self.status, to_status, reason))
        self.status = to_status
        return self.status

    @property
    def terminal(self) -> bool:
        return self.status in {
            RunStatus.APPROVED,
            RunStatus.REJECTED,
            RunStatus.AWAITING_HUMAN,
            RunStatus.ESCALATION_ERROR,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
        }

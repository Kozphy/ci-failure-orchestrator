"""Governed AI agent pipeline package.

Composes existing CI reliability primitives into an explicit,
production-oriented control flow without replacing prior stacks.
"""

from .models import FailureEvent, PipelineState, PolicyOutcome
from .pipeline import GovernedAgentPipeline, PipelineResult, failure_event_from_dict
from .state_machine import IllegalTransitionError, PipelineStateMachine

__all__ = [
    "FailureEvent",
    "GovernedAgentPipeline",
    "IllegalTransitionError",
    "PipelineResult",
    "PipelineState",
    "PipelineStateMachine",
    "PolicyOutcome",
    "failure_event_from_dict",
]

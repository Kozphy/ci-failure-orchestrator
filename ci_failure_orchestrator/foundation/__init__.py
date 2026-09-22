"""Agent execution foundation (Phases 2–13).

Phase 10 adds durable state, append-oriented audit events, and evidence refs
when ``artifacts_root`` is configured.

Phase 12 adds the deterministic synthetic benchmark harness under
``foundation.benchmark``.

Phase 13 adds observability metrics / SLI / SLO under ``foundation.observability``.
"""

from .escalation import (
    EscalationArtifactWriter,
    HumanEscalation,
    HumanEscalationBuilder,
    ReviewerAction,
)
from .models import FailureEvent, RunStatus
from .persistence import (
    inspect_run,
    replay_events,
    resume_run,
    verify_run_consistency,
)
from .policy import PolicyConfig, PolicyDecision, PolicyOutcome, StaticPolicyEngine
from .runner import AgentExecutionFoundation, FoundationResult, ScriptedProposalFactory
from .state_machine import FoundationStateMachine, InvalidStateTransition

__all__ = [
    "AgentExecutionFoundation",
    "EscalationArtifactWriter",
    "FailureEvent",
    "FoundationResult",
    "FoundationStateMachine",
    "HumanEscalation",
    "HumanEscalationBuilder",
    "InvalidStateTransition",
    "PolicyConfig",
    "PolicyDecision",
    "PolicyOutcome",
    "ReviewerAction",
    "RunStatus",
    "ScriptedProposalFactory",
    "StaticPolicyEngine",
    "inspect_run",
    "replay_events",
    "resume_run",
    "verify_run_consistency",
]

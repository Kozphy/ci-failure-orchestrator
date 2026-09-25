"""Foundation run outcome."""

from __future__ import annotations

from dataclasses import dataclass, field

from .escalation import HumanEscalation
from .models import RunState, RunStatus
from .policy import PolicyDecision, PolicyOutcome
from .retry import RetryDecision, RetryReason


@dataclass
class FoundationResult:
    """Run outcome including Phase 7–9 metrics."""

    run: RunState
    status: RunStatus
    attempts: int = 0
    retries: int = 0
    stop_reason: RetryReason | None = None
    duplicate_proposal_count: int = 0
    duplicate_failure_count: int = 0
    no_progress_count: int = 0
    decisions: list[RetryDecision] = field(default_factory=list)
    technical_status: str = "FAIL"  # PASS | FAIL
    policy_outcome: PolicyOutcome | None = None
    policy_decision: PolicyDecision | None = None
    workflow_status: str | None = None
    escalation: HumanEscalation | None = None
    escalation_id: str | None = None
    artifact_refs: dict[str, str] = field(default_factory=dict)

    def explain(self) -> str:
        parts = list(self.run.retry_trace)
        parts.extend(self.run.policy_trace)
        if self.escalation is not None:
            parts.append(self.escalation.summary)
        if not parts:
            return self.status.value
        return "\n".join(parts)

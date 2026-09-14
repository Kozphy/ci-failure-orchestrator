"""Bounded repair state machine for autonomous CI recovery.

The state machine coordinates policy-approved repair attempts without granting the
worker release authority. It records immutable transition evidence and stops on
success, denial, review requirements, or exhausted budgets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
from json import dumps
from typing import Callable, Iterable

from .github_repair_adapter import AgentTask, FailedCheck, GitHubRepairPlan, build_repair_plan
from .supervisor import RepairAuthority, SupervisorPolicy
from .task_idempotency import DeliveryOutcome, IdempotentTaskDeliverer


class RepairState(str, Enum):
    """Lifecycle state for one CI repair incident."""

    DETECTED = "detected"
    PLANNED = "planned"
    DISPATCHED = "dispatched"
    VERIFYING = "verifying"
    RERUNNING = "rerunning"
    GREEN = "green"
    REVIEW_REQUIRED = "review_required"
    ESCALATED = "escalated"
    DENIED = "denied"


@dataclass(frozen=True)
class Transition:
    """Tamper-evident state transition."""

    sequence: int
    from_state: RepairState
    to_state: RepairState
    reason: str
    digest: str


@dataclass
class RepairIncident:
    """Mutable incident aggregate with append-only transition history."""

    incident_id: str
    check: FailedCheck
    state: RepairState = RepairState.DETECTED
    attempt: int = 0
    cost_spent_usd: float = 0.0
    elapsed_seconds: int = 0
    transitions: list[Transition] = field(default_factory=list)

    def transition(self, to_state: RepairState, reason: str) -> Transition:
        """Move the incident and append a chained transition digest."""

        previous_digest = self.transitions[-1].digest if self.transitions else "GENESIS"
        payload = {
            "incident_id": self.incident_id,
            "sequence": len(self.transitions) + 1,
            "from": self.state.value,
            "to": to_state.value,
            "reason": reason,
            "previous_digest": previous_digest,
        }
        digest = sha256(dumps(payload, sort_keys=True).encode()).hexdigest()
        transition = Transition(
            sequence=payload["sequence"],
            from_state=self.state,
            to_state=to_state,
            reason=reason,
            digest=digest,
        )
        self.transitions.append(transition)
        self.state = to_state
        return transition


@dataclass(frozen=True)
class WorkerResult:
    """Provider-neutral result returned by a coding agent."""

    patch_proposed: bool
    changed_paths: tuple[str, ...] = ()
    changed_lines: int = 0
    cost_usd: float = 0.0
    regression_detected: bool = False
    test_weakening_detected: bool = False
    security_finding: bool = False


@dataclass(frozen=True)
class VerificationResult:
    """Independent verification result and canonical repair-success contract.

    A repair is successful only when every positive gate passes and neither test
    weakening nor regression is detected. Agent self-report cannot set success.
    """

    targeted_tests_passed: bool
    full_regression_passed: bool
    policy_gate_passed: bool
    ci_green: bool
    security_gate_passed: bool = True
    test_weakening_detected: bool = False
    regression_detected: bool = False

    @property
    def successful(self) -> bool:
        """Return the single canonical definition of verified repair success."""

        return (
            self.ci_green
            and self.targeted_tests_passed
            and self.full_regression_passed
            and self.security_gate_passed
            and self.policy_gate_passed
            and not self.test_weakening_detected
            and not self.regression_detected
        )


class RepairCoordinator:
    """Coordinate one bounded repair loop using provider-neutral contracts."""

    def __init__(self, policy: SupervisorPolicy | None = None) -> None:
        self.policy = policy or SupervisorPolicy()

    def plan(self, incident: RepairIncident) -> GitHubRepairPlan:
        """Build the next repair plan and update incident lifecycle state."""

        incident.attempt += 1
        plan = build_repair_plan(
            incident.check,
            attempt=incident.attempt,
            cost_spent_usd=incident.cost_spent_usd,
            elapsed_seconds=incident.elapsed_seconds,
            policy=self.policy,
        )
        if plan.decision.authority is RepairAuthority.DENY:
            incident.transition(RepairState.DENIED, ",".join(plan.decision.reasons))
        elif plan.decision.authority is RepairAuthority.RCA_ONLY:
            incident.transition(RepairState.ESCALATED, "rca_only")
        else:
            incident.transition(RepairState.PLANNED, plan.decision.authority.value)
        return plan

    def dispatch(self, incident: RepairIncident, task: AgentTask) -> None:
        """Record worker dispatch; the coordinator never executes the worker itself."""

        if incident.state is not RepairState.PLANNED:
            raise RuntimeError("incident must be planned before dispatch")
        if not task.idempotency_key:
            raise ValueError("AgentTask.idempotency_key is required before dispatch")
        incident.transition(RepairState.DISPATCHED, task.authority.value)

    def deliver_idempotent(
        self,
        incident: RepairIncident,
        task: AgentTask,
        side_effect: Callable[[AgentTask], WorkerResult],
        deliverer: IdempotentTaskDeliverer,
    ) -> DeliveryOutcome[WorkerResult]:
        """Dispatch a worker through the durable completion ledger.

        The accepted side effect (``side_effect``) runs at most once per
        ``task.idempotency_key``. Duplicate or post-crash redelivery replays the
        stored ``WorkerResult`` without invoking the side effect again.
        """

        if not task.idempotency_key:
            raise ValueError("AgentTask.idempotency_key is required")

        def _accepted_side_effect(bound_task: AgentTask) -> dict:
            result = side_effect(bound_task)
            return asdict(result)

        outcome = deliverer.deliver(task, _accepted_side_effect)
        worker_result = _worker_result_from_payload(outcome.result)

        # Advance incident only when still awaiting dispatch (first success or
        # crash after ledger completion but before local state transition).
        if incident.state is RepairState.PLANNED:
            self.dispatch(incident, task)
            self.accept_worker_result(incident, worker_result)

        return DeliveryOutcome(
            idempotency_key=outcome.idempotency_key,
            executed=outcome.executed,
            replayed=outcome.replayed,
            result=worker_result,
            status=outcome.status,
        )

    def accept_worker_result(self, incident: RepairIncident, result: WorkerResult) -> None:
        """Apply worker accounting and move to independent verification."""

        if incident.state is not RepairState.DISPATCHED:
            raise RuntimeError("worker result requires dispatched state")
        incident.cost_spent_usd += result.cost_usd
        if result.regression_detected or result.test_weakening_detected or result.security_finding:
            incident.transition(RepairState.DENIED, "worker_result_failed_safety_gate")
            return
        if not result.patch_proposed:
            incident.transition(RepairState.ESCALATED, "worker_proposed_no_patch")
            return
        incident.transition(RepairState.VERIFYING, "candidate_patch_ready")

    def verify(self, incident: RepairIncident, result: VerificationResult) -> None:
        """Apply canonical independent verification and finish or retry safely."""

        if incident.state is not RepairState.VERIFYING:
            raise RuntimeError("verification requires verifying state")
        if result.test_weakening_detected or result.regression_detected:
            incident.transition(RepairState.DENIED, "verification_detected_unsafe_repair")
            return
        if not result.security_gate_passed:
            incident.transition(RepairState.DENIED, "security_gate_failed")
            return
        if not result.targeted_tests_passed or not result.full_regression_passed:
            incident.transition(RepairState.RERUNNING, "tests_failed")
            return
        if not result.policy_gate_passed:
            incident.transition(RepairState.REVIEW_REQUIRED, "policy_gate_requires_review")
            return
        if result.successful:
            incident.transition(RepairState.GREEN, "canonical_success_predicate_satisfied")
            return
        incident.transition(RepairState.RERUNNING, "ci_still_red")

    def prepare_retry(self, incident: RepairIncident) -> None:
        """Return a rerunning incident to detected state for the next bounded attempt."""

        if incident.state is not RepairState.RERUNNING:
            raise RuntimeError("retry requires rerunning state")
        incident.transition(RepairState.DETECTED, "bounded_retry")


def verify_transition_chain(transitions: Iterable[Transition]) -> bool:
    """Validate sequence monotonicity and non-empty transition digests."""

    previous = 0
    for transition in transitions:
        if transition.sequence != previous + 1 or len(transition.digest) != 64:
            return False
        previous = transition.sequence
    return True


def _worker_result_from_payload(payload: object) -> WorkerResult:
    """Rehydrate a ``WorkerResult`` from ledger JSON (lists → tuples)."""

    if isinstance(payload, WorkerResult):
        return payload
    if not isinstance(payload, dict):
        raise TypeError(f"expected WorkerResult payload dict, got {type(payload)!r}")
    return WorkerResult(
        patch_proposed=bool(payload["patch_proposed"]),
        changed_paths=tuple(payload.get("changed_paths") or ()),
        changed_lines=int(payload.get("changed_lines") or 0),
        cost_usd=float(payload.get("cost_usd") or 0.0),
        regression_detected=bool(payload.get("regression_detected") or False),
        test_weakening_detected=bool(payload.get("test_weakening_detected") or False),
        security_finding=bool(payload.get("security_finding") or False),
    )

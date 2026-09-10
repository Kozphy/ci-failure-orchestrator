from __future__ import annotations

"""Multi-repository fleet management for CI repair orchestration.

This module provides repository policy management and fleet-level decision
coordination. It evaluates repository snapshots against registered policies
and determines whether each repository should repair, queue, freeze, or be denied.

Module responsibility:
    - Maintain repository-specific automation policies
    - Evaluate repository snapshots against policies
    - Aggregate individual decisions into fleet-wide state
    - Enforce safety boundaries (error-budget burn, canary health, concurrency)

Key invariants:
    - Unregistered repositories are automatically denied
    - Disabled automation repositories are denied regardless of state
    - Error-budget burn triggers freeze (non-overrideable)
    - Unhealthy canary triggers freeze (non-overrideable)
    - Concurrency limits trigger queue (not immediate freeze)
    - No failures means idle

Safety boundaries:
    - freeze_on_error_budget_burn: burn threshold that triggers freeze (default 2.0)
    - max_concurrent_repairs: per-repository repair limit from policy
    - require_human_on: policy-defined human approval threshold

Failure modes:
    - Repository not registered: action="deny", reason="repository is not registered"
    - Automation disabled: action="deny", reason="automation is disabled"
    - Error budget exceeded: action="freeze", reason="SLO error budget burn exceeded"
    - Canary unhealthy: action="freeze", reason="canary is unhealthy"
    - Concurrency limit: action="queue", reason="repository repair concurrency limit reached"
    - No failures: action="idle", reason="no actionable failures"
    - Failures present and policy permits: action="repair", reason="fleet policy permits bounded repair"

Fleet state derivation:
    - FROZEN: any repository has action="freeze"
    - DEGRADED: any repository has action in {"repair", "queue", "deny"}
    - HEALTHY: all repositories idle
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class FleetState(str, Enum):
    """Overall health state of the fleet.

    Values:
        HEALTHY: All repositories idle (no actionable failures)
        DEGRADED: At least one repository is repairing, queued, or denied
        FROZEN: At least one repository is frozen (SLO burn or canary failure)
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FROZEN = "frozen"


@dataclass(frozen=True)
class RepositoryPolicy:
    """Configuration for a single repository's automation behavior.

    Defines how the fleet manager should handle a specific repository,
    including whether automation is enabled, autonomy limits, concurrency
    constraints, and escalation thresholds.

    Attributes:
        repository: Unique identifier for the repository (e.g., "org/repo")
        enabled: Whether automation is permitted for this repository
        autonomy_level: Level of autonomous action permitted ("low", "medium", "high")
        max_concurrent_repairs: Maximum simultaneous repairs allowed
        require_human_on: Risk level at which human approval is required
        canary_group: Canary deployment group assignment
    """

    repository: str
    enabled: bool = True
    autonomy_level: str = "medium"
    max_concurrent_repairs: int = 1
    require_human_on: str = "high-risk"
    canary_group: str = "default"


@dataclass(frozen=True)
class RepositorySnapshot:
    """Current state snapshot for a repository.

    Captures the dynamic state of a repository at evaluation time,
    including failure count, active repair count, and health indicators.

    Attributes:
        repository: Unique identifier matching a registered policy
        open_failures: Number of unresolved failures requiring attention
        active_repairs: Number of repairs currently in progress
        error_budget_burn: Current SLO error-budget consumption ratio
        canary_healthy: Whether the canary deployment for this repo is healthy
    """

    repository: str
    open_failures: int = 0
    active_repairs: int = 0
    error_budget_burn: float = 0.0
    canary_healthy: bool = True


@dataclass(frozen=True)
class FleetDecision:
    """Decision for a single repository from fleet evaluation.

    Attributes:
        repository: Repository identifier this decision applies to
        action: One of "repair", "queue", "freeze", "deny", "idle"
        reason: Human-readable explanation for the decision
    """

    repository: str
    action: str
    reason: str


@dataclass
class FleetManager:
    """Coordinator for multi-repository repair policy and state evaluation.

    Maintains a registry of repository policies and evaluates current
    repository snapshots against those policies to produce decisions.

    Responsibility:
        - Register and store repository policies
        - Evaluate repository snapshots against policies
        - Aggregate decisions into fleet-wide state

    Invariants:
        - Policy lookup is case-sensitive on repository identifier
        - Evaluation order is deterministic (iterates snapshots in order)
        - Freeze conditions (SLO burn, canary) take precedence over all others

    Usage:
        manager = FleetManager()
        manager.register(RepositoryPolicy("org/repo", enabled=True))
        decisions = manager.evaluate([RepositorySnapshot("org/repo", open_failures=1)])
        state = manager.state(snapshots)

    Side effects:
        - register() mutates internal policy registry
        - evaluate() and state() are pure functions from inputs

    Audit Notes:
        - Policy registration is append-only; later registrations override earlier ones
        - Evaluation decisions are deterministic given the same inputs
        - freeze_on_error_budget_burn is a global threshold; per-repo override not supported
    """

    policies: dict[str, RepositoryPolicy] = field(default_factory=dict)
    freeze_on_error_budget_burn: float = 2.0

    def register(self, policy: RepositoryPolicy) -> None:
        """Register a repository policy.

        Args:
            policy: RepositoryPolicy to register

        Side effects:
            Adds or replaces the policy for policy.repository in the registry.
        """
        self.policies[policy.repository] = policy

    def evaluate(self, snapshots: Iterable[RepositorySnapshot]) -> list[FleetDecision]:
        """Evaluate repository snapshots and return decisions.

        Applies policy checks in priority order:
        1. Repository not registered -> deny
        2. Automation disabled -> deny
        3. Error budget burn >= threshold -> freeze
        4. Canary unhealthy -> freeze
        5. Concurrency limit reached -> queue
        6. No open failures -> idle
        7. Otherwise -> repair

        Args:
            snapshots: Iterable of current repository states

        Returns:
            List of FleetDecision, one per snapshot, in input order

        Side effects:
            None. Decisions are derived from current state.

        Audit Notes:
            - Freeze decisions cannot be overridden by other conditions
            - Queue decisions preserve concurrency boundaries
            - Idle is only returned when open_failures <= 0
        """

        decisions: list[FleetDecision] = []
        for snapshot in snapshots:
            policy = self.policies.get(snapshot.repository)
            if policy is None:
                decisions.append(FleetDecision(snapshot.repository, "deny", "repository is not registered"))
                continue
            if not policy.enabled:
                decisions.append(FleetDecision(snapshot.repository, "deny", "automation is disabled"))
                continue
            if snapshot.error_budget_burn >= self.freeze_on_error_budget_burn:
                decisions.append(FleetDecision(snapshot.repository, "freeze", "SLO error budget burn exceeded"))
                continue
            if not snapshot.canary_healthy:
                decisions.append(FleetDecision(snapshot.repository, "freeze", "canary is unhealthy"))
                continue
            if snapshot.active_repairs >= policy.max_concurrent_repairs:
                decisions.append(FleetDecision(snapshot.repository, "queue", "repository repair concurrency limit reached"))
                continue
            if snapshot.open_failures <= 0:
                decisions.append(FleetDecision(snapshot.repository, "idle", "no actionable failures"))
                continue
            decisions.append(FleetDecision(snapshot.repository, "repair", "fleet policy permits bounded repair"))
        return decisions

    def state(self, snapshots: Iterable[RepositorySnapshot]) -> FleetState:
        """Derive overall fleet state from repository decisions.

        State is determined by evaluating all snapshots and checking
        for the presence of freeze, repair/queue/deny, or idle actions.

        Args:
            snapshots: Iterable of current repository states

        Returns:
            FleetState.HEALTHY if all repositories are idle
            FleetState.FROZEN if any repository has action="freeze"
            FleetState.DEGRADED otherwise (any repair/queue/deny)

        Side effects:
            None. State is derived from decisions.
        """
        decisions = self.evaluate(snapshots)
        if any(d.action == "freeze" for d in decisions):
            return FleetState.FROZEN
        if any(d.action in {"repair", "queue", "deny"} for d in decisions):
            return FleetState.DEGRADED
        return FleetState.HEALTHY

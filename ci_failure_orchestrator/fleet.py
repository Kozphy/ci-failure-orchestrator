"""Fleet management for multi-repository CI repair orchestration.

This module provides the fleet-level control plane for managing autonomous repair
across multiple repositories, including policy enforcement, concurrency limits,
error-budget monitoring, and canary health checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class FleetState(str, Enum):
    """Overall health state of the repair fleet.

    Attributes:
        HEALTHY: All repositories are idle or healthy.
        DEGRADED: Some repositories have active repairs or issues.
        FROZEN: Fleet-wide freeze due to SLO violations or canary failures.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FROZEN = "frozen"


@dataclass(frozen=True)
class RepositoryPolicy:
    """Policy configuration for a single repository in the fleet.

    Attributes:
        repository: Repository identifier (e.g., "owner/repo").
        enabled: Whether automation is enabled for this repository.
        autonomy_level: Autonomy level (e.g., "low", "medium", "high").
        max_concurrent_repairs: Maximum number of concurrent repair operations.
        require_human_on: Risk level requiring human approval.
        canary_group: Canary group for staged rollouts.
    """

    repository: str
    enabled: bool = True
    autonomy_level: str = "medium"
    max_concurrent_repairs: int = 1
    require_human_on: str = "high-risk"
    canary_group: str = "default"


@dataclass(frozen=True)
class RepositorySnapshot:
    """Current state snapshot of a repository for fleet evaluation.

    Attributes:
        repository: Repository identifier.
        open_failures: Number of unresolved CI failures.
        active_repairs: Number of currently active repair operations.
        error_budget_burn: Current error-budget burn rate (1.0 = budget exhausted).
        canary_healthy: Whether the canary deployment is healthy.
    """

    repository: str
    open_failures: int = 0
    active_repairs: int = 0
    error_budget_burn: float = 0.0
    canary_healthy: bool = True


@dataclass(frozen=True)
class FleetDecision:
    """Fleet-level decision for a repository.

    Attributes:
        repository: Repository identifier.
        action: Action to take (e.g., "repair", "freeze", "queue", "deny", "idle").
        reason: Human-readable explanation for the decision.
    """

    repository: str
    action: str
    reason: str


@dataclass
class FleetManager:
    """Manages policy and decisions across a fleet of repositories.

    The FleetManager enforces repository-specific policies, evaluates fleet-wide
    health, and decides whether to permit, queue, deny, or freeze autonomous repair
    operations based on error-budget burn, canary health, and concurrency limits.

    Attributes:
        policies: Mapping of repository IDs to their policies.
        freeze_on_error_budget_burn: Error-budget burn threshold that triggers fleet freeze.

    Audit Notes:
        - Wrong decisions can block legitimate repairs or allow unsafe operations.
        - Freeze decisions are based on error-budget burn and canary health.
        - Recovery: Review error-budget calculations and canary metrics before unfreezing.
        - Evidence: Fleet decisions are logged with reasons for audit trails.
    """

    policies: dict[str, RepositoryPolicy] = field(default_factory=dict)
    freeze_on_error_budget_burn: float = 2.0

    def register(self, policy: RepositoryPolicy) -> None:
        """Register a repository policy with the fleet manager.

        Args:
            policy: Repository policy to register.
        """
        self.policies[policy.repository] = policy

    def evaluate(self, snapshots: Iterable[RepositorySnapshot]) -> list[FleetDecision]:
        """Evaluate repository snapshots and determine fleet actions.

        Args:
            snapshots: Iterable of repository state snapshots.

        Returns:
            List of fleet decisions for each repository snapshot.

        Decision Logic:
            - deny: Repository not registered or automation disabled.
            - freeze: Error-budget burn exceeded or canary unhealthy.
            - queue: Concurrency limit reached.
            - idle: No actionable failures.
            - repair: Fleet policy permits bounded repair.
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
        """Determine overall fleet state from repository snapshots.

        Args:
            snapshots: Iterable of repository state snapshots.

        Returns:
            Fleet state (HEALTHY, DEGRADED, or FROZEN).

        State Logic:
            - FROZEN: Any repository requires freeze action.
            - DEGRADED: Any repository has active repairs, queue, or deny actions.
            - HEALTHY: All repositories are idle.
        """
        decisions = self.evaluate(snapshots)
        if any(d.action == "freeze" for d in decisions):
            return FleetState.FROZEN
        if any(d.action in {"repair", "queue", "deny"} for d in decisions):
            return FleetState.DEGRADED
        return FleetState.HEALTHY

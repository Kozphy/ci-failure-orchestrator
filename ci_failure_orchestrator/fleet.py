from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class FleetState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FROZEN = "frozen"


@dataclass(frozen=True)
class RepositoryPolicy:
    repository: str
    enabled: bool = True
    autonomy_level: str = "medium"
    max_concurrent_repairs: int = 1
    require_human_on: str = "high-risk"
    canary_group: str = "default"


@dataclass(frozen=True)
class RepositorySnapshot:
    repository: str
    open_failures: int = 0
    active_repairs: int = 0
    error_budget_burn: float = 0.0
    canary_healthy: bool = True


@dataclass(frozen=True)
class FleetDecision:
    repository: str
    action: str
    reason: str


@dataclass
class FleetManager:
    policies: dict[str, RepositoryPolicy] = field(default_factory=dict)
    freeze_on_error_budget_burn: float = 2.0

    def register(self, policy: RepositoryPolicy) -> None:
        self.policies[policy.repository] = policy

    def evaluate(self, snapshots: Iterable[RepositorySnapshot]) -> list[FleetDecision]:
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
        decisions = self.evaluate(snapshots)
        if any(d.action == "freeze" for d in decisions):
            return FleetState.FROZEN
        if any(d.action in {"repair", "queue", "deny"} for d in decisions):
            return FleetState.DEGRADED
        return FleetState.HEALTHY

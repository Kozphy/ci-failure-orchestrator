from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .software_factory import AgentRuntime, FactoryTask
from .telemetry import MetricsRegistry, Timer


_RISK_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class ProviderRoute:
    name: str
    max_risk: str
    estimated_cost_usd: float

    def supports(self, task: FactoryTask) -> bool:
        if self.max_risk not in _RISK_RANK or task.risk not in _RISK_RANK:
            raise ValueError("unsupported risk level")
        return _RISK_RANK[task.risk] <= _RISK_RANK[self.max_risk]


@dataclass
class BudgetLedger:
    limit_usd: float
    spent_usd: float = 0.0

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def can_spend(self, amount_usd: float) -> bool:
        if amount_usd < 0:
            raise ValueError("amount_usd must be >= 0")
        return self.spent_usd + amount_usd <= self.limit_usd

    def charge(self, amount_usd: float) -> None:
        if not self.can_spend(amount_usd):
            raise RuntimeError("factory budget exceeded")
        self.spent_usd += amount_usd


class CostAwareModelRouter:
    """Select the cheapest provider that satisfies risk and budget constraints."""

    def __init__(self, routes: tuple[ProviderRoute, ...]) -> None:
        if not routes:
            raise ValueError("at least one provider route is required")
        self.routes = routes

    def choose(self, task: FactoryTask, ledger: BudgetLedger) -> ProviderRoute:
        candidates = [
            route
            for route in self.routes
            if route.supports(task) and ledger.can_spend(route.estimated_cost_usd)
        ]
        if not candidates:
            raise RuntimeError(
                f"no provider route satisfies risk={task.risk} within remaining budget"
            )
        return min(candidates, key=lambda route: (route.estimated_cost_usd, route.name))


class BudgetedRuntimeRouter:
    """Route autonomous work to agents while enforcing task economics.

    Provider costs are explicit estimates. Execution remains behind AgentRuntime
    adapters, so the control plane is independent of Codex/Cursor/Claude/etc.
    """

    def __init__(
        self,
        runtimes: Mapping[str, AgentRuntime],
        router: CostAwareModelRouter,
        ledger: BudgetLedger,
        *,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self.runtimes = dict(runtimes)
        self.router = router
        self.ledger = ledger
        self.metrics = metrics or MetricsRegistry()

    def execute(self, task: FactoryTask) -> None:
        route = self.router.choose(task, self.ledger)
        try:
            runtime = self.runtimes[route.name]
        except KeyError as exc:
            raise KeyError(f"runtime not configured for provider: {route.name}") from exc

        self.metrics.inc("factory_task_attempts")
        self.metrics.inc(f"factory_provider_selected.{route.name}")
        with Timer(self.metrics, "factory_agent_latency_ms"):
            runtime.execute(task)

        self.ledger.charge(route.estimated_cost_usd)
        self.metrics.inc("factory_estimated_cost_usd", route.estimated_cost_usd)


@dataclass(frozen=True)
class FactoryMetricsSnapshot:
    task_attempts: int
    estimated_cost_usd: float
    provider_counts: dict[str, int]
    latency_samples_ms: tuple[float, ...]


def snapshot_metrics(registry: MetricsRegistry) -> FactoryMetricsSnapshot:
    provider_counts = {
        key.removeprefix("factory_provider_selected."): int(value)
        for key, value in registry.counters.items()
        if key.startswith("factory_provider_selected.")
    }
    return FactoryMetricsSnapshot(
        task_attempts=int(registry.counters.get("factory_task_attempts", 0.0)),
        estimated_cost_usd=float(registry.counters.get("factory_estimated_cost_usd", 0.0)),
        provider_counts=provider_counts,
        latency_samples_ms=tuple(registry.observations.get("factory_agent_latency_ms", ())),
    )

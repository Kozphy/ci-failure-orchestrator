"""Economic routing and operational telemetry for autonomous factory agents.

The control plane treats model choice and autonomous spend as policy inputs,
not agent preferences. Routes declare their risk capability and estimated
cost, the budget ledger enforces a hard spend ceiling, and runtime execution
records provider-selection and latency evidence for later analysis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .software_factory import AgentRuntime, FactoryTask
from .telemetry import MetricsRegistry, Timer


_RISK_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class ProviderRoute:
    """Describe one provider's autonomous risk capability and estimated cost."""

    name: str
    max_risk: str
    estimated_cost_usd: float

    def supports(self, task: FactoryTask) -> bool:
        """Return whether this provider is authorized for ``task`` risk.

        Raises:
            ValueError: If either route or task uses an unsupported risk level.
        """
        if self.max_risk not in _RISK_RANK or task.risk not in _RISK_RANK:
            raise ValueError("unsupported risk level")
        return _RISK_RANK[task.risk] <= _RISK_RANK[self.max_risk]


@dataclass
class BudgetLedger:
    """Track estimated autonomous spend against a hard factory budget."""

    limit_usd: float
    spent_usd: float = 0.0

    @property
    def remaining_usd(self) -> float:
        """Return non-negative remaining autonomous budget."""
        return max(0.0, self.limit_usd - self.spent_usd)

    def can_spend(self, amount_usd: float) -> bool:
        """Return whether ``amount_usd`` fits within the remaining budget."""
        if amount_usd < 0:
            raise ValueError("amount_usd must be >= 0")
        return self.spent_usd + amount_usd <= self.limit_usd

    def charge(self, amount_usd: float) -> None:
        """Record estimated spend or fail closed when the budget is exceeded."""
        if not self.can_spend(amount_usd):
            raise RuntimeError("factory budget exceeded")
        self.spent_usd += amount_usd


class CostAwareModelRouter:
    """Select the cheapest provider satisfying risk and budget constraints.

    The router is deterministic for equal-cost candidates by using provider
    name as a tie breaker. It never escalates to an over-budget or under-
    privileged provider merely to keep autonomous execution moving.
    """

    def __init__(self, routes: tuple[ProviderRoute, ...]) -> None:
        """Initialize the router with at least one explicit provider route."""
        if not routes:
            raise ValueError("at least one provider route is required")
        self.routes = routes

    def choose(self, task: FactoryTask, ledger: BudgetLedger) -> ProviderRoute:
        """Choose the least-cost eligible route for ``task``.

        Raises:
            RuntimeError: If no route satisfies both risk and remaining budget.
        """
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
    """Execute tasks through routed agents while enforcing economics.

    Provider costs are explicit estimates. Runtime implementations remain
    behind :class:`AgentRuntime`, so the control plane stays independent of
    Codex, Cursor, Claude, Gemini, or future workers. Spend is charged only
    after the configured runtime returns successfully.
    """

    def __init__(
        self,
        runtimes: Mapping[str, AgentRuntime],
        router: CostAwareModelRouter,
        ledger: BudgetLedger,
        *,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        """Bind provider names to runtimes, routing policy, budget, and metrics."""
        self.runtimes = dict(runtimes)
        self.router = router
        self.ledger = ledger
        self.metrics = metrics or MetricsRegistry()

    def execute(self, task: FactoryTask) -> None:
        """Route and execute one task, then charge and record telemetry.

        Raises:
            KeyError: If the selected provider has no configured runtime.
            RuntimeError: Propagated when no eligible route or budget exists.
        """
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
    """Immutable aggregate view of factory routing and execution telemetry."""

    task_attempts: int
    estimated_cost_usd: float
    provider_counts: dict[str, int]
    latency_samples_ms: tuple[float, ...]


def snapshot_metrics(registry: MetricsRegistry) -> FactoryMetricsSnapshot:
    """Convert mutable metric counters into a stable reporting snapshot."""
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

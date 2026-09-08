from __future__ import annotations

import pytest

from ci_failure_orchestrator.factory_control_plane import (
    BudgetedRuntimeRouter,
    BudgetLedger,
    CostAwareModelRouter,
    ProviderRoute,
    snapshot_metrics,
)
from ci_failure_orchestrator.software_factory import FactoryTask


class RecordingRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, task: FactoryTask) -> None:
        self.calls.append(task.id)


def test_router_selects_cheapest_provider_that_satisfies_risk() -> None:
    router = CostAwareModelRouter(
        (
            ProviderRoute("cheap", "low", 0.10),
            ProviderRoute("strong", "high", 0.80),
        )
    )
    ledger = BudgetLedger(limit_usd=2.0)

    assert router.choose(FactoryTask(id="a", title="a", goal="a", risk="low"), ledger).name == "cheap"
    assert router.choose(FactoryTask(id="b", title="b", goal="b", risk="high"), ledger).name == "strong"


def test_router_fails_closed_when_budget_cannot_cover_task() -> None:
    router = CostAwareModelRouter((ProviderRoute("strong", "high", 1.0),))
    ledger = BudgetLedger(limit_usd=0.5)

    with pytest.raises(RuntimeError, match="remaining budget"):
        router.choose(FactoryTask(id="x", title="x", goal="x", risk="medium"), ledger)


def test_budgeted_runtime_records_cost_provider_and_latency() -> None:
    cheap = RecordingRuntime()
    strong = RecordingRuntime()
    ledger = BudgetLedger(limit_usd=2.0)
    runtime = BudgetedRuntimeRouter(
        runtimes={"cheap": cheap, "strong": strong},
        router=CostAwareModelRouter(
            (
                ProviderRoute("cheap", "low", 0.10),
                ProviderRoute("strong", "high", 0.80),
            )
        ),
        ledger=ledger,
    )

    runtime.execute(FactoryTask(id="low", title="low", goal="low", risk="low"))
    runtime.execute(FactoryTask(id="high", title="high", goal="high", risk="high"))

    snapshot = snapshot_metrics(runtime.metrics)
    assert cheap.calls == ["low"]
    assert strong.calls == ["high"]
    assert ledger.spent_usd == pytest.approx(0.90)
    assert snapshot.task_attempts == 2
    assert snapshot.estimated_cost_usd == pytest.approx(0.90)
    assert snapshot.provider_counts == {"cheap": 1, "strong": 1}
    assert len(snapshot.latency_samples_ms) == 2


def test_missing_runtime_configuration_fails_closed_without_charging() -> None:
    ledger = BudgetLedger(limit_usd=1.0)
    runtime = BudgetedRuntimeRouter(
        runtimes={},
        router=CostAwareModelRouter((ProviderRoute("codex", "high", 0.4),)),
        ledger=ledger,
    )

    with pytest.raises(KeyError, match="runtime not configured"):
        runtime.execute(FactoryTask(id="x", title="x", goal="x", risk="low"))

    assert ledger.spent_usd == 0.0

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .benchmark_suite import BenchmarkResult, BenchmarkSuite, BenchmarkSummary
from .canary import CanaryDecision, CanaryMetrics, CanaryPolicy, evaluate_canary
from .dashboard import DashboardSnapshot, build_dashboard_snapshot
from .fleet import FleetDecision, FleetManager, FleetState, RepositorySnapshot
from .slo import SLOObservation, SLOReport, SLOTarget, evaluate_slo


@dataclass(frozen=True)
class PlatformReport:
    fleet_state: FleetState
    fleet_decisions: tuple[FleetDecision, ...]
    benchmark: BenchmarkSummary
    slo: SLOReport
    canary: CanaryDecision
    dashboard: DashboardSnapshot


class CIRepairPlatform:
    """Fleet-level control plane for v1.0 CI repair operations.

    This layer never bypasses repository-level repair policy. It aggregates
    independent evidence and decides whether the fleet may continue, hold,
    or freeze autonomous repair activity.
    """

    def __init__(
        self,
        fleet: FleetManager,
        slo_target: SLOTarget | None = None,
        canary_policy: CanaryPolicy | None = None,
    ) -> None:
        self.fleet = fleet
        self.slo_target = slo_target or SLOTarget()
        self.canary_policy = canary_policy or CanaryPolicy()

    def evaluate(
        self,
        *,
        repositories: Iterable[RepositorySnapshot],
        benchmark_results: Iterable[BenchmarkResult],
        slo_observation: SLOObservation,
        canary_metrics: CanaryMetrics,
    ) -> PlatformReport:
        repository_rows = list(repositories)
        decisions = tuple(self.fleet.evaluate(repository_rows))
        fleet_state = self.fleet.state(repository_rows)
        benchmark = BenchmarkSuite.summarize(benchmark_results)
        slo = evaluate_slo(self.slo_target, slo_observation)
        canary = evaluate_canary(canary_metrics, self.canary_policy)

        if canary == CanaryDecision.ROLLBACK or not slo.met:
            fleet_state = FleetState.FROZEN

        dashboard = build_dashboard_snapshot(
            fleet_state=fleet_state,
            decisions=decisions,
            slo=slo,
            benchmark=benchmark,
        )
        return PlatformReport(
            fleet_state=fleet_state,
            fleet_decisions=decisions,
            benchmark=benchmark,
            slo=slo,
            canary=canary,
            dashboard=dashboard,
        )

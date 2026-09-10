"""Platform-level control plane for CI repair operations.

This module provides the integrated platform façade that combines fleet policy,
benchmark evidence, SLO evaluation, canary evaluation, and dashboard generation
into a unified fleet-level control path.
"""

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
    """Comprehensive report from platform-level evaluation.

    Attributes:
        fleet_state: Overall health state of the repair fleet.
        fleet_decisions: Tuple of fleet decisions for each repository.
        benchmark: Benchmark summary metrics.
        slo: SLO evaluation report.
        canary: Canary promotion decision.
        dashboard: Dashboard snapshot for visualization.
    """

    fleet_state: FleetState
    fleet_decisions: tuple[FleetDecision, ...]
    benchmark: BenchmarkSummary
    slo: SLOReport
    canary: CanaryDecision
    dashboard: DashboardSnapshot


class CIRepairPlatform:
    """Fleet-level control plane for v1.0 CI repair operations.

    This layer aggregates independent evidence from fleet policy, benchmarks,
    SLOs, and canaries to decide whether the fleet may continue, hold, or freeze
    autonomous repair activity. It never bypasses repository-level repair policy.

    The platform enforces separation of duties: repair agents may propose changes,
    but release authority remains with evaluation, regression checks, repository
    policy, canary health, fleet policy, SLOs, and human approval.

    Attributes:
        fleet: FleetManager for repository policy and fleet decisions.
        slo_target: SLO targets for availability, repair success, latency, etc.
        canary_policy: Canary promotion policy thresholds.

    Audit Notes:
        - Platform decisions can freeze autonomous repair across the entire fleet.
        - Freeze conditions include SLO violations and canary rollbacks.
        - Recovery: Review SLO calculations, canary metrics, and benchmark evidence.
        - Evidence: All platform decisions produce auditable reports and dashboard snapshots.
    """

    def __init__(
        self,
        fleet: FleetManager,
        slo_target: SLOTarget | None = None,
        canary_policy: CanaryPolicy | None = None,
    ) -> None:
        """Initialize the CI repair platform.

        Args:
            fleet: FleetManager instance for fleet-level control.
            slo_target: Optional SLO targets. Defaults to conservative SLOTarget.
            canary_policy: Optional canary policy. Defaults to conservative CanaryPolicy.
        """
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
        """Evaluate fleet state and produce a comprehensive platform report.

        This method combines fleet decisions, benchmark evidence, SLO evaluation,
        and canary evaluation to determine whether autonomous repair should continue.
        SLO violations or canary rollbacks trigger an immediate fleet freeze.

        Args:
            repositories: Iterable of repository state snapshots.
            benchmark_results: Iterable of benchmark results from repair operations.
            slo_observation: Observed SLO metrics (availability, repair success, latency).
            canary_metrics: Canary deployment metrics (success rate, regression rate).

        Returns:
            PlatformReport containing fleet state, decisions, benchmark summary,
            SLO report, canary decision, and dashboard snapshot.

        Side Effects:
            - May override fleet state to FROZEN if SLOs are not met or canary requires rollback.
            - Generates dashboard snapshot for visualization and audit.
        """
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

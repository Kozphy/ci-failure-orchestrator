from __future__ import annotations

"""Fleet-level control plane for the CI Repair Platform.

This module provides the top-level orchestration layer that integrates:
- Fleet management with repository-specific policies
- Benchmark evidence aggregation
- SLO evaluation with error-budget tracking
- Canary deployment health assessment
- Dashboard snapshot generation

The control plane enforces separation of duties: it aggregates evidence and
coordinates decisions, but never bypasses repository-level policy or
autonomous repair boundaries.

Module responsibility:
    - Orchestrate fleet-level evaluation across multiple repositories
    - Aggregate independent evidence (benchmarks, SLOs, canaries)
    - Enforce fleet-wide safety invariants (freeze on SLO burn, canary failure)
    - Produce machine-readable platform reports for downstream consumption

Key invariants:
    - Repository policy remains authoritative; platform cannot override it
    - Canary rollback or SLO violation triggers fleet-wide freeze
    - All decisions are evidence-backed and auditable
    - Platform state is derived, not stored

Failure modes:
    - If canary evaluation returns ROLLBACK: fleet_state becomes FROZEN
    - If SLO evaluation fails (not met): fleet_state becomes FROZEN
    - If evaluation inputs are invalid: raises ValueError (fail-fast)

Safety boundaries:
    - No direct repository mutation
    - No autonomous decision overriding
    - Read-only aggregation of pre-computed evidence
"""

from dataclasses import dataclass
from typing import Iterable

from .benchmark_suite import BenchmarkResult, BenchmarkSuite, BenchmarkSummary
from .canary import CanaryDecision, CanaryMetrics, CanaryPolicy, evaluate_canary
from .dashboard import DashboardSnapshot, build_dashboard_snapshot
from .fleet import FleetDecision, FleetManager, FleetState, RepositorySnapshot
from .slo import SLOObservation, SLOReport, SLOTarget, evaluate_slo


@dataclass(frozen=True)
class PlatformReport:
    """Immutable snapshot of platform evaluation results.

    Combines fleet state, per-repository decisions, benchmark summary, SLO report,
    canary decision, and dashboard snapshot into a single auditable artifact.

    Attributes:
        fleet_state: Overall fleet health state (HEALTHY, DEGRADED, FROZEN)
        fleet_decisions: Per-repository repair/queue/deny/freeze decisions
        benchmark: Aggregated benchmark metrics across all repair cases
        slo: SLO compliance report with error-budget burn calculation
        canary: Canary deployment decision (PROMOTE, HOLD, ROLLBACK)
        dashboard: Pre-computed dashboard snapshot for UI/consumption
    """

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

    Responsibility:
        - Coordinate cross-repository repair policy evaluation
        - Aggregate benchmark, SLO, and canary evidence
        - Enforce fleet-wide safety gates (SLO burn, canary health)
        - Produce platform-level reports for observability

    Invariants:
        - Repository policy is always respected; platform cannot override deny/freeze
        - Fleet state is derived from repository decisions + global gates
        - SLO or canary failure triggers immediate fleet freeze

    Usage:
        platform = CIRepairPlatform(fleet)
        report = platform.evaluate(
            repositories=[...],
            benchmark_results=[...],
            slo_observation=...,
            canary_metrics=...,
        )

    Side effects:
        None. This class performs pure computation from inputs.

    Audit Notes:
        - All inputs must be pre-computed; platform does not fetch live data
        - Fleet freeze decisions are auditable via report.fleet_state
        - PlatformReport is immutable and hashable for evidence chains
    """

    def __init__(
        self,
        fleet: FleetManager,
        slo_target: SLOTarget | None = None,
        canary_policy: CanaryPolicy | None = None,
    ) -> None:
        """Initialize the platform with fleet manager and optional policies.

        Args:
            fleet: FleetManager instance with registered repository policies
            slo_target: Target SLO thresholds; defaults to standard targets
            canary_policy: Canary promotion/rollback policy; defaults to standard
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

        Performs independent evaluation of:
        - Fleet decisions for each repository snapshot
        - Fleet state aggregation
        - Benchmark summary computation
        - SLO compliance check
        - Canary decision
        - Dashboard snapshot build

        If canary decision is ROLLBACK or SLO is not met, fleet_state is forced
        to FROZEN regardless of individual repository decisions.

        Args:
            repositories: Current snapshots of repository states
            benchmark_results: Results from benchmark suite runs
            slo_observation: Observed SLO metrics from the field
            canary_metrics: Current canary deployment health metrics

        Returns:
            PlatformReport containing all evaluation results and derived state

        Raises:
            ValueError: If benchmark_results is empty (cannot compute summary)

        Side effects:
            None. All evaluation is derived from inputs.

        Audit Notes:
            - Fleet freeze on SLO/canary failure is automatic and non-overrideable
            - All decisions are traceable through the returned report
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

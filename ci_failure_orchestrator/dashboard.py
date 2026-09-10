from __future__ import annotations

"""Dashboard snapshot generation for CI repair platform.

This module provides dashboard data aggregation that is deliberately
UI-independent. The snapshot can feed terminal reports, JSON artifacts,
Grafana/Prometheus exporters, or web dashboards without coupling control
logic to presentation code.

Module responsibility:
    - Aggregate fleet, SLO, and benchmark data into dashboard format
    - Provide machine-readable snapshot for downstream consumption
    - Count repository states for fleet overview

Key invariants:
    - DashboardSnapshot is immutable (frozen dataclass)
    - All counts are derived from FleetDecision actions
    - Dashboard data is a pure function of inputs

Safety boundaries:
    - No direct system calls or external dependencies
    - All computation is deterministic from inputs

Audit Notes:
    - DashboardSnapshot.to_dict() provides JSON-serializable output
    - All metrics are pre-computed; no lazy evaluation
"""

from dataclasses import asdict, dataclass
from typing import Iterable

from .benchmark_suite import BenchmarkSummary
from .fleet import FleetDecision, FleetState
from .slo import SLOReport


@dataclass(frozen=True)
class DashboardSnapshot:
    """Immutable dashboard snapshot for fleet state visualization.

    Contains all metrics needed to display fleet health, repair quality,
    and platform performance in a UI-independent format.

    Attributes:
        fleet_state: Overall fleet health ("healthy", "degraded", "frozen")
        repositories_total: Total number of repositories in fleet
        repositories_repairing: Count of repositories with action="repair"
        repositories_frozen: Count of repositories with action="freeze"
        repositories_queued: Count of repositories with action="queue"
        slo_met: Whether SLO targets are currently satisfied
        error_budget_burn: Current error-budget consumption ratio
        repair_success_rate: Aggregated repair success rate from benchmarks
        false_repair_rate: Aggregated false repair rate from benchmarks
        root_cause_top1_accuracy: Top-1 root cause identification accuracy
        root_cause_top3_accuracy: Top-3 root cause identification accuracy
        p95_repair_latency_ms: 95th percentile repair latency in milliseconds
    """

    fleet_state: str
    repositories_total: int
    repositories_repairing: int
    repositories_frozen: int
    repositories_queued: int
    slo_met: bool
    error_budget_burn: float
    repair_success_rate: float
    false_repair_rate: float
    root_cause_top1_accuracy: float
    root_cause_top3_accuracy: float
    p95_repair_latency_ms: float

    def to_dict(self) -> dict[str, object]:
        """Return JSON-serializable dictionary representation.

        Returns:
            Dictionary with all dashboard metrics
        """
        return asdict(self)


def build_dashboard_snapshot(
    fleet_state: FleetState,
    decisions: Iterable[FleetDecision],
    slo: SLOReport,
    benchmark: BenchmarkSummary,
) -> DashboardSnapshot:
    """Build a dashboard snapshot from fleet, SLO, and benchmark data.

    Aggregates decision counts and extracts metrics from SLO and benchmark
    reports to produce a complete dashboard snapshot.

    Args:
        fleet_state: Current fleet-wide state
        decisions: Iterable of per-repository decisions
        slo: SLOReport from latest evaluation
        benchmark: BenchmarkSummary from latest benchmark run

    Returns:
        DashboardSnapshot with all aggregated metrics

    Side effects:
        None. Pure computation from inputs.

    Audit Notes:
        - Decision counts are computed by iterating all decisions
        - All metrics are extracted from provided reports
    """

    rows = list(decisions)
    return DashboardSnapshot(
        fleet_state=fleet_state.value,
        repositories_total=len(rows),
        repositories_repairing=sum(d.action == "repair" for d in rows),
        repositories_frozen=sum(d.action == "freeze" for d in rows),
        repositories_queued=sum(d.action == "queue" for d in rows),
        slo_met=slo.met,
        error_budget_burn=slo.error_budget_burn,
        repair_success_rate=benchmark.repair_success_rate,
        false_repair_rate=benchmark.false_repair_rate,
        root_cause_top1_accuracy=benchmark.root_cause_accuracy,
        root_cause_top3_accuracy=benchmark.top3_root_cause_accuracy,
        p95_repair_latency_ms=benchmark.p95_latency_ms,
    )

"""Fleet dashboard snapshot generation for CI repair telemetry.

This module provides dashboard snapshot generation that combines fleet decisions,
SLO state, and benchmark evidence into a machine-readable snapshot for
visualization and monitoring. The snapshot is UI-independent and can feed
terminal reports, JSON artifacts, Grafana/Prometheus exporters, or web dashboards.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .benchmark_suite import BenchmarkSummary
from .fleet import FleetDecision, FleetState
from .slo import SLOReport


@dataclass(frozen=True)
class DashboardSnapshot:
    """Machine-readable snapshot of fleet health and repair performance.

    This snapshot combines fleet decisions, SLO state, and benchmark evidence
    into a unified view suitable for dashboard visualization and monitoring.
    The structure is UI-independent to support multiple presentation formats.

    Attributes:
        fleet_state: Overall fleet state (healthy, degraded, or frozen).
        repositories_total: Total number of repositories in the fleet.
        repositories_repairing: Number of repositories currently undergoing repair.
        repositories_frozen: Number of repositories frozen due to SLO or canary issues.
        repositories_queued: Number of repositories queued due to concurrency limits.
        slo_met: Whether SLO targets are being met across the fleet.
        error_budget_burn: Current error-budget burn rate (1.0 = budget exhausted).
        repair_success_rate: Fleet-wide repair success rate from benchmarks.
        false_repair_rate: Fleet-wide false repair rate from benchmarks.
        root_cause_top1_accuracy: Top-1 root-cause identification accuracy.
        root_cause_top3_accuracy: Top-3 root-cause identification accuracy.
        p95_repair_latency_ms: 95th percentile repair latency in milliseconds.
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
        """Convert the dashboard snapshot to a dictionary representation.

        Returns:
            Dictionary containing all snapshot fields for JSON serialization.
        """
        return asdict(self)


def build_dashboard_snapshot(
    fleet_state: FleetState,
    decisions: Iterable[FleetDecision],
    slo: SLOReport,
    benchmark: BenchmarkSummary,
) -> DashboardSnapshot:
    """Build a dashboard snapshot from fleet, SLO, and benchmark data.

    This function aggregates fleet decisions, SLO evaluation results, and
    benchmark metrics into a unified snapshot for dashboard visualization
    and monitoring. The snapshot provides a comprehensive view of fleet health,
    repair performance, and SLO compliance.

    Args:
        fleet_state: Overall fleet state (healthy, degraded, or frozen).
        decisions: Iterable of fleet decisions for each repository.
        slo: SLO evaluation report with metrics and violations.
        benchmark: Benchmark summary with repair performance metrics.

    Returns:
        DashboardSnapshot with aggregated fleet health and performance metrics.

    Metrics Aggregated:
        - Repository counts by action (repair, freeze, queue, total)
        - SLO compliance status and error-budget burn
        - Repair success rate and false repair rate from benchmarks
        - Root-cause accuracy (top-1 and top-3)
        - 95th percentile repair latency

    Audit Notes:
        - Dashboard snapshots provide visibility into fleet health and repair performance.
        - Incorrect snapshot data could hide SLO violations or performance degradation.
        - Recovery: Verify SLO calculations and benchmark aggregation if metrics seem incorrect.
        - Evidence: All snapshots include source data (fleet decisions, SLO, benchmarks) for audit.
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

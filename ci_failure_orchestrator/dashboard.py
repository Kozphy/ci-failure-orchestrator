from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .benchmark_suite import BenchmarkSummary
from .fleet import FleetDecision, FleetState
from .slo import SLOReport


@dataclass(frozen=True)
class DashboardSnapshot:
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
        return asdict(self)


def build_dashboard_snapshot(
    fleet_state: FleetState,
    decisions: Iterable[FleetDecision],
    slo: SLOReport,
    benchmark: BenchmarkSummary,
) -> DashboardSnapshot:
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

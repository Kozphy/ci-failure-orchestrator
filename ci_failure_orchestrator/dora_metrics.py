from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import median
from typing import Iterable


@dataclass(frozen=True)
class DeploymentEvent:
    deployment_id: str
    commit_sha: str
    started_at: datetime
    completed_at: datetime
    succeeded: bool
    rollback_performed: bool = False
    recovered_at: datetime | None = None

    @property
    def lead_time_seconds(self) -> float:
        return max(0.0, (self.completed_at - self.started_at).total_seconds())

    @property
    def recovery_time_seconds(self) -> float | None:
        if self.succeeded or self.recovered_at is None:
            return None
        return max(0.0, (self.recovered_at - self.completed_at).total_seconds())


@dataclass(frozen=True)
class DoraMetrics:
    deployment_count: int
    successful_deployments: int
    failed_deployments: int
    deployment_frequency_per_day: float
    median_lead_time_seconds: float
    change_fail_rate: float
    median_recovery_time_seconds: float | None
    rollback_rate: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def calculate_dora_metrics(events: Iterable[DeploymentEvent]) -> DoraMetrics:
    ordered = sorted(events, key=lambda e: e.started_at)
    if not ordered:
        raise ValueError("at least one deployment event is required")

    deployment_count = len(ordered)
    failed = [e for e in ordered if not e.succeeded]
    succeeded = deployment_count - len(failed)
    rollbacks = [e for e in ordered if e.rollback_performed]
    recovery_times = [e.recovery_time_seconds for e in failed if e.recovery_time_seconds is not None]

    first = ordered[0].started_at
    last = ordered[-1].completed_at
    elapsed_days = max((last - first).total_seconds() / 86400.0, 1.0)

    return DoraMetrics(
        deployment_count=deployment_count,
        successful_deployments=succeeded,
        failed_deployments=len(failed),
        deployment_frequency_per_day=deployment_count / elapsed_days,
        median_lead_time_seconds=median(e.lead_time_seconds for e in ordered),
        change_fail_rate=len(failed) / deployment_count,
        median_recovery_time_seconds=(median(recovery_times) if recovery_times else None),
        rollback_rate=len(rollbacks) / deployment_count,
    )

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SLOTarget:
    availability: float = 0.99
    repair_success_rate: float = 0.90
    p95_repair_latency_ms: int = 300_000
    false_repair_rate: float = 0.02


@dataclass(frozen=True)
class SLOObservation:
    total_runs: int
    successful_runs: int
    successful_repairs: int
    attempted_repairs: int
    false_repairs: int
    p95_repair_latency_ms: int

    @property
    def availability(self) -> float:
        return self.successful_runs / self.total_runs if self.total_runs else 1.0

    @property
    def repair_success_rate(self) -> float:
        return self.successful_repairs / self.attempted_repairs if self.attempted_repairs else 1.0

    @property
    def false_repair_rate(self) -> float:
        return self.false_repairs / self.attempted_repairs if self.attempted_repairs else 0.0


@dataclass(frozen=True)
class SLOReport:
    met: bool
    availability: float
    repair_success_rate: float
    false_repair_rate: float
    p95_repair_latency_ms: int
    error_budget_burn: float
    violations: tuple[str, ...]


def evaluate_slo(target: SLOTarget, observation: SLOObservation) -> SLOReport:
    violations: list[str] = []
    if observation.availability < target.availability:
        violations.append("availability")
    if observation.repair_success_rate < target.repair_success_rate:
        violations.append("repair_success_rate")
    if observation.false_repair_rate > target.false_repair_rate:
        violations.append("false_repair_rate")
    if observation.p95_repair_latency_ms > target.p95_repair_latency_ms:
        violations.append("p95_repair_latency")

    allowed_unavailability = max(1e-9, 1.0 - target.availability)
    observed_unavailability = max(0.0, 1.0 - observation.availability)
    burn = observed_unavailability / allowed_unavailability

    return SLOReport(
        met=not violations,
        availability=observation.availability,
        repair_success_rate=observation.repair_success_rate,
        false_repair_rate=observation.false_repair_rate,
        p95_repair_latency_ms=observation.p95_repair_latency_ms,
        error_budget_burn=burn,
        violations=tuple(violations),
    )

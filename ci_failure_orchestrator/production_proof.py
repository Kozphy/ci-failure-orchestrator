from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


@dataclass(frozen=True)
class ProductionMetrics:
    repair_success_rate: float
    regression_rate: float
    p95_latency_seconds: float
    cost_per_success_usd: float
    critical_security_findings: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProductionPolicy:
    min_repair_success_rate: float = 0.90
    max_regression_rate: float = 0.02
    max_p95_latency_seconds: float = 30.0
    max_cost_per_success_usd: float = 0.20
    max_critical_security_findings: int = 0


@dataclass(frozen=True)
class GateResult:
    passed: bool
    checks: dict[str, bool]

    @property
    def decision(self) -> str:
        return "PASS" if self.passed else "BLOCK"

    def to_dict(self) -> dict:
        return {"passed": self.passed, "decision": self.decision, "checks": self.checks}


def evaluate_production_gate(
    metrics: ProductionMetrics,
    policy: ProductionPolicy | None = None,
) -> GateResult:
    policy = policy or ProductionPolicy()
    checks = {
        "repair_success_rate": metrics.repair_success_rate >= policy.min_repair_success_rate,
        "regression_rate": metrics.regression_rate <= policy.max_regression_rate,
        "p95_latency_seconds": metrics.p95_latency_seconds <= policy.max_p95_latency_seconds,
        "cost_per_success_usd": metrics.cost_per_success_usd <= policy.max_cost_per_success_usd,
        "critical_security_findings": metrics.critical_security_findings <= policy.max_critical_security_findings,
    }
    return GateResult(passed=all(checks.values()), checks=checks)


def metrics_from_mapping(data: Mapping[str, object]) -> ProductionMetrics:
    return ProductionMetrics(
        repair_success_rate=float(data["repair_success_rate"]),
        regression_rate=float(data["regression_rate"]),
        p95_latency_seconds=float(data["p95_latency_seconds"]),
        cost_per_success_usd=float(data["cost_per_success_usd"]),
        critical_security_findings=int(data.get("critical_security_findings", 0)),
    )

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean, median
from typing import Callable, Iterable

from .control_plane import ControlPlaneRun, RunStatus
from .models import Failure


@dataclass(frozen=True)
class RepairBenchmarkCase:
    name: str
    failure: Failure
    expected: RunStatus


@dataclass(frozen=True)
class RepairBenchmarkResult:
    name: str
    status: str
    expected: str
    passed: bool
    cost: float
    latency_ms: float
    retries: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RepairBenchmarkSummary:
    cases: int
    passed: int
    success_rate: float
    mean_cost: float
    median_latency_ms: float
    total_retries: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_repairs(
    cases: Iterable[RepairBenchmarkCase],
    run_factory: Callable[[Failure], ControlPlaneRun],
) -> tuple[list[RepairBenchmarkResult], RepairBenchmarkSummary]:
    results: list[RepairBenchmarkResult] = []

    for case in cases:
        run = run_factory(case.failure)
        status = run.status
        telemetry = run.telemetry()
        results.append(
            RepairBenchmarkResult(
                name=case.name,
                status=status.value,
                expected=case.expected.value,
                passed=status is case.expected,
                cost=telemetry["cost_usd"],
                latency_ms=telemetry["latency_ms"],
                retries=telemetry["retries_used"],
            )
        )

    count = len(results)
    passed = sum(item.passed for item in results)
    summary = RepairBenchmarkSummary(
        cases=count,
        passed=passed,
        success_rate=round(passed / count, 4) if count else 0.0,
        mean_cost=round(mean(item.cost for item in results), 6) if results else 0.0,
        median_latency_ms=round(median(item.latency_ms for item in results), 3) if results else 0.0,
        total_retries=sum(item.retries for item in results),
    )
    return results, summary

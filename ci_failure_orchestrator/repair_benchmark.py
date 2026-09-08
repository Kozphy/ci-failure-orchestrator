from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean, median
from typing import Callable, Iterable

from .control_plane import Decision, RepairControlPlane
from .models import Failure


@dataclass(frozen=True)
class RepairBenchmarkCase:
    name: str
    failure: Failure
    expected: Decision


@dataclass(frozen=True)
class RepairBenchmarkResult:
    name: str
    decision: str
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
    control_factory: Callable[[], RepairControlPlane],
) -> tuple[list[RepairBenchmarkResult], RepairBenchmarkSummary]:
    results: list[RepairBenchmarkResult] = []

    for case in cases:
        control = control_factory()
        decision = control.run(case.failure)
        state = control.last_state
        results.append(
            RepairBenchmarkResult(
                name=case.name,
                decision=decision.value,
                expected=case.expected.value,
                passed=decision is case.expected,
                cost=state.total_cost if state else 0.0,
                latency_ms=state.total_latency_ms if state else 0.0,
                retries=state.retries_used if state else 0,
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

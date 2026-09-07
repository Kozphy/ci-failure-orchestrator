from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean

from .repair import RepairAttempt, RepairPlanner, SandboxRepairExecutor


@dataclass(frozen=True)
class RepairRun:
    case_id: str
    resolved: bool
    attempts: tuple[RepairAttempt, ...]
    escalated: bool

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "resolved": self.resolved,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "escalated": self.escalated,
        }


@dataclass(frozen=True)
class RepairMetrics:
    cases: int
    repair_success_rate: float
    first_attempt_success_rate: float
    mean_attempts: float
    regression_rate: float
    escalation_rate: float
    p50_latency_seconds: float
    p95_latency_seconds: float

    def to_dict(self) -> dict:
        return asdict(self)


def run_repair_case(
    fixture_dir: Path,
    case: dict,
    planner: RepairPlanner,
    executor: SandboxRepairExecutor,
    retry_budget: int = 2,
) -> RepairRun:
    attempts: list[RepairAttempt] = []
    for plan in planner.plan(case)[: max(retry_budget, 0)]:
        attempt = executor.run(fixture_dir, case, plan)
        attempts.append(attempt)
        if attempt.success and not attempt.regression_detected:
            return RepairRun(case_id=case["id"], resolved=True, attempts=tuple(attempts), escalated=False)
    return RepairRun(case_id=case["id"], resolved=False, attempts=tuple(attempts), escalated=True)


def summarize_repair_runs(runs: list[RepairRun]) -> RepairMetrics:
    if not runs:
        return RepairMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    resolved = sum(run.resolved for run in runs)
    first = sum(bool(run.attempts and run.attempts[0].success and not run.attempts[0].regression_detected) for run in runs)
    all_attempts = [attempt for run in runs for attempt in run.attempts]
    regressions = sum(attempt.regression_detected for attempt in all_attempts)
    latencies = sorted(sum(attempt.duration_seconds for attempt in run.attempts) for run in runs)

    def percentile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        index = min(len(values) - 1, round((len(values) - 1) * q))
        return round(values[index], 6)

    return RepairMetrics(
        cases=len(runs),
        repair_success_rate=round(resolved / len(runs), 4),
        first_attempt_success_rate=round(first / len(runs), 4),
        mean_attempts=round(mean(len(run.attempts) for run in runs), 4),
        regression_rate=round(regressions / max(len(all_attempts), 1), 4),
        escalation_rate=round(sum(run.escalated for run in runs) / len(runs), 4),
        p50_latency_seconds=percentile(latencies, 0.50),
        p95_latency_seconds=percentile(latencies, 0.95),
    )

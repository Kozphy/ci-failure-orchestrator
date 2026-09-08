from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .repair import RepairPlanner, SandboxRepairExecutor
from .repair_loop import run_repair_case, summarize_repair_runs


@dataclass(frozen=True)
class AblationResult:
    system: str
    metrics: dict

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_repair_ablations(cases: list[dict], fixture_root: Path, executor_factory) -> list[AblationResult]:
    configs = [
        ("heuristic_single_attempt", 1),
        ("repair_plus_evaluator", 1),
        ("full_orchestrator_retry", 2),
    ]
    results: list[AblationResult] = []
    for name, retry_budget in configs:
        runs = []
        for case in cases:
            fixture = fixture_root / case["fixture"]
            planner = RepairPlanner()
            executor: SandboxRepairExecutor = executor_factory(case)
            runs.append(run_repair_case(fixture, case, planner, executor, retry_budget=retry_budget))
        results.append(AblationResult(system=name, metrics=summarize_repair_runs(runs).to_dict()))
    return results

from __future__ import annotations
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class BenchmarkResult:
    cases: int
    top1_accuracy: float
    top3_accuracy: float
    mean_cascade_elimination: float

    def to_dict(self):
        return asdict(self)


def evaluate_cases(cases: list[dict], rank_fn) -> BenchmarkResult:
    if not cases:
        return BenchmarkResult(0, 0.0, 0.0, 0.0)
    top1 = 0
    top3 = 0
    cascade: list[float] = []
    for case in cases:
        ranked = rank_fn(case)
        stages = [item.failure.stage for item in ranked]
        truth = case["root_cause"]
        top1 += bool(stages and stages[0] == truth)
        top3 += truth in stages[:3]
        before = set(case.get("failed_before", []))
        after = set(case.get("failed_after_fix", []))
        downstream = before - {truth}
        cascade.append((len(downstream - after) / len(downstream)) if downstream else 1.0)
    count = len(cases)
    return BenchmarkResult(count, round(top1 / count, 4), round(top3 / count, 4), round(sum(cascade) / count, 4))

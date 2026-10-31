"""Evaluate authored synthetic cases; repeated timings are not independent cases."""

import hashlib
import json
import math
import platform
import statistics
import sys
import time
from pathlib import Path

from .core import Claim, Engine, Evidence, Recommendation, Risk

CASES = Path(__file__).with_name("cases.json")


def run_case(case):
    system = Engine()
    system.register(Claim("c1", "Synthetic repair is usable", "fixture", ("repair", "gap", "other"),
                          "behavior regresses"), "owner", 100)
    for index, group in enumerate(case["groups"]):
        payload = f"synthetic measurement {index}".encode()
        system.add_evidence(Evidence(f"e{index}", "c1", f"source{index}", group, payload,
                                    hashlib.sha256(payload).hexdigest(), case.get("stance", "supports"),
                                    case.get("captured_at", 1), case.get("attested", True)), "owner")
    for _ in range(case.get("prior_evaluations", 0)):
        system.evaluate("c1", Risk(), now=2)
    return system.evaluate("c1", Risk(**case.get("risk", {})), now=case.get("now", 2),
                           cost=case.get("cost", 0))


def evaluate(repeats=100):
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    results, durations = [], []
    for case in cases:
        case_times = []
        observed = None
        for _ in range(repeats):
            start = time.perf_counter_ns()
            observed = run_case(case)
            case_times.append((time.perf_counter_ns() - start) / 1_000_000)
        durations.extend(case_times)
        results.append(dict(case_id=case["id"], expected=case["expected"],
                            observed=observed.recommendation.value,
                            agrees=observed.recommendation.value == case["expected"],
                            spent_synthetic_units=observed.spent, attempts=observed.attempts))
    proceed = Recommendation.PROCEED_REVERSIBLY.value
    nonproceed = sum(c["expected"] != proceed for c in cases)
    return dict(schema_version="edas-evaluation.v1", fixture_sha256=hashlib.sha256(CASES.read_bytes()).hexdigest(),
                provenance="authored synthetic cases; not an independent or representative sample",
                python=sys.version, platform=platform.platform(), case_count=len(cases),
                agreement=dict(numerator=sum(r["agrees"] for r in results), denominator=len(cases)),
                green_only_baseline_agreement=dict(numerator=sum(c["expected"] == proceed for c in cases),
                                                    denominator=len(cases)),
                unsafe_proceed=dict(numerator=sum(r["observed"] == proceed and r["expected"] != proceed
                                                  for r in results), denominator=nonproceed),
                baseline_unsafe_proceed=dict(numerator=nonproceed, denominator=nonproceed),
                timings=dict(unit="ms", includes="in-memory fixture creation and evaluation; no I/O",
                             repeats_per_case=repeats, total_measurements=len(durations),
                             median=statistics.median(durations),
                             p95_nearest_rank=sorted(durations)[math.ceil(0.95 * len(durations)) - 1]),
                provider_cost="not applicable: no model or network calls", results=results)


if __name__ == "__main__":
    report = evaluate()
    print(json.dumps(report, indent=2, sort_keys=True))
    sys.exit(int(report["agreement"]["numerator"] != report["agreement"]["denominator"]))

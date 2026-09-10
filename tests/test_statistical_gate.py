from ci_failure_orchestrator.benchmark_suite import BenchmarkResult
from ci_failure_orchestrator.statistical_gate import (
    StatisticalGatePolicy,
    evaluate_statistical_gate,
    wilson_interval,
)


def _result(case_id: str, *, repaired: bool = True, regression: bool = False, false_repair: bool = False) -> BenchmarkResult:
    return BenchmarkResult(
        case_id=case_id,
        root_stage_correct=True,
        repaired=repaired,
        regression=regression,
        escalated=False,
        retries=0,
        cost=0.01,
        latency_ms=100.0,
        false_repair=false_repair,
    )


def test_wilson_interval_is_bounded_and_contains_estimate() -> None:
    interval = wilson_interval(90, 100)
    assert 0.0 <= interval.lower <= interval.estimate <= interval.upper <= 1.0
    assert interval.estimate == 0.9


def test_gate_blocks_small_sample_despite_perfect_results() -> None:
    rows = [_result(str(index)) for index in range(10)]
    gate = evaluate_statistical_gate(
        rows,
        StatisticalGatePolicy(
            min_cases=50,
            min_repair_success_rate=0.80,
            max_regression_rate=0.30,
            max_false_repair_rate=0.30,
        ),
    )
    assert gate.passed is False
    assert gate.checks["minimum_sample_size"] is False


def test_gate_passes_when_confidence_bounds_clear_policy() -> None:
    rows = [_result(str(index)) for index in range(200)]
    gate = evaluate_statistical_gate(
        rows,
        StatisticalGatePolicy(
            min_cases=100,
            min_repair_success_rate=0.95,
            max_regression_rate=0.02,
            max_false_repair_rate=0.02,
        ),
    )
    assert gate.passed is True
    assert gate.repair_success.lower >= 0.95
    assert gate.regression.upper <= 0.02


def test_gate_blocks_when_risk_upper_bound_is_too_high() -> None:
    rows = [_result(str(index)) for index in range(190)] + [
        _result(f"bad-{index}", regression=True, false_repair=True)
        for index in range(10)
    ]
    gate = evaluate_statistical_gate(
        rows,
        StatisticalGatePolicy(
            min_cases=100,
            min_repair_success_rate=0.85,
            max_regression_rate=0.05,
            max_false_repair_rate=0.05,
        ),
    )
    assert gate.passed is False
    assert gate.checks["regression_upper_bound"] is False
    assert gate.checks["false_repair_upper_bound"] is False


def test_gate_handles_empty_evidence_by_failing_closed() -> None:
    gate = evaluate_statistical_gate([])
    assert gate.passed is False
    assert gate.cases == 0
    assert gate.repair_success.lower == 0.0
    assert gate.regression.upper == 1.0

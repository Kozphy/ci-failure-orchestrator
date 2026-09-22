"""Phase 12 — benchmark harness unit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci_failure_orchestrator.foundation.benchmark.assertions import (
    evaluate_expectations,
    scan_secrets_in_tree,
)
from ci_failure_orchestrator.foundation.benchmark.baseline import (
    RegressionLabel,
    compare_to_baseline,
)
from ci_failure_orchestrator.foundation.benchmark.injection import (
    BenchmarkInjectionError,
    InjectingSandbox,
)
from ci_failure_orchestrator.foundation.benchmark.loader import filter_cases, load_suite
from ci_failure_orchestrator.foundation.benchmark.metrics import (
    MetricResult,
    case_pass_rate,
    classification_accuracy,
    compute_suite_metrics,
    false_remediation_count,
    policy_outcome_accuracy,
    repair_success_rate,
)
from ci_failure_orchestrator.foundation.benchmark.report import render_markdown, write_reports
from ci_failure_orchestrator.foundation.benchmark.runner import BenchmarkRunner
from ci_failure_orchestrator.foundation.benchmark.schemas import (
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkAssertionResult,
    BenchmarkCase,
    BenchmarkCaseResult,
    ExpectedResult,
    FailureInjectionSpec,
    ObservedResult,
)
from ci_failure_orchestrator.foundation.sandbox import TempCopySandboxExecutor


CASES_DIR = Path(__file__).resolve().parents[1] / "benchmarks" / "foundation" / "cases"


def test_schema_version() -> None:
    assert BENCHMARK_SCHEMA_VERSION.startswith("foundation.benchmark")


def test_load_suite_and_stable_ids() -> None:
    cases = load_suite(CASES_DIR)
    assert len(cases) >= 20
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids))
    assert all(c.case_id.startswith("BENCH-") for c in cases)
    assert all(c.synthetic for c in cases)


def test_filter_cases() -> None:
    cases = load_suite(CASES_DIR)
    sec = filter_cases(cases, category="SECURITY")
    assert sec and all(c.category == "SECURITY" for c in sec)
    one = filter_cases(cases, case_id="BENCH-REPAIR-001")
    assert len(one) == 1
    req = filter_cases(cases, required=True)
    assert all(c.required for c in req)


def test_metric_zero_denominator() -> None:
    m = classification_accuracy([])
    assert m.denominator == 0
    assert m.value is None
    assert "n/a" in m.to_dict()["display"]


def test_metric_all_pass_fail() -> None:
    passed = [
        BenchmarkCaseResult(
            case_id="a",
            passed=True,
            duration_ms=1,
            populations=("classification",),
            assertions=[
                BenchmarkAssertionResult("classification", True, "x", "x")
            ],
        )
    ]
    failed = [
        BenchmarkCaseResult(
            case_id="b",
            passed=False,
            duration_ms=1,
            populations=("classification",),
            assertions=[
                BenchmarkAssertionResult("classification", False, "x", "y")
            ],
        )
    ]
    assert case_pass_rate(passed).value == 1.0
    assert case_pass_rate(failed).value == 0.0
    assert classification_accuracy(passed).numerator == 1
    assert classification_accuracy(failed).numerator == 0


def test_repair_and_policy_metrics_populations() -> None:
    results = [
        BenchmarkCaseResult(
            case_id="r1",
            passed=True,
            duration_ms=1,
            populations=("repairable", "policy"),
            observed={"technical_status": "PASS", "policy_outcome": "APPROVE"},
            assertions=[
                BenchmarkAssertionResult("policy_outcome", True, "APPROVE", "APPROVE")
            ],
        ),
        BenchmarkCaseResult(
            case_id="r2",
            passed=False,
            duration_ms=1,
            populations=("repairable",),
            observed={"technical_status": "FAIL"},
        ),
    ]
    assert repair_success_rate(results).numerator == 1
    assert repair_success_rate(results).denominator == 2
    assert policy_outcome_accuracy(results).numerator == 1


def test_false_remediation() -> None:
    results = [
        BenchmarkCaseResult(
            case_id="f",
            passed=False,
            duration_ms=1,
            observed={"technical_status": "PASS"},
        )
    ]
    assert false_remediation_count(results).numerator == 1


def test_baseline_comparison_labels() -> None:
    results = [
        BenchmarkCaseResult("A", True, 1.0),
        BenchmarkCaseResult("B", False, 1.0),
        BenchmarkCaseResult("C", True, 1.0),
    ]
    baseline = {
        "cases": {
            "A": {"passed": True},
            "B": {"passed": True},
            "D": {"passed": False},
        }
    }
    deltas = {d.case_id: d.label for d in compare_to_baseline(results, baseline)}
    assert deltas["A"] is RegressionLabel.UNCHANGED_PASS
    assert deltas["B"] is RegressionLabel.REGRESSED
    assert deltas["C"] is RegressionLabel.NEW_CASE
    assert deltas["D"] is RegressionLabel.REMOVED_CASE

    improved = compare_to_baseline(
        [BenchmarkCaseResult("B", True, 1.0)],
        {"cases": {"B": {"passed": False}}},
    )
    assert improved[0].label is RegressionLabel.IMPROVED

    unchanged_fail = compare_to_baseline(
        [BenchmarkCaseResult("B", False, 1.0)],
        {"cases": {"B": {"passed": False}}},
    )
    assert unchanged_fail[0].label is RegressionLabel.UNCHANGED_FAIL


def test_injection_requires_benchmark_mode() -> None:
    with pytest.raises(BenchmarkInjectionError):
        InjectingSandbox(
            TempCopySandboxExecutor(),
            spec=FailureInjectionSpec(target="sandbox", failure="timeout"),
            benchmark_mode=False,
        )


def test_assertion_engine() -> None:
    expected = ExpectedResult(
        policy_outcome="ESCALATE",
        attempts=2,
        secrets_absent=("SECRET",),
    )
    observed = ObservedResult(
        policy_outcome="ESCALATE",
        attempts=2,
        secrets_leaked=(),
    )
    asserts = evaluate_expectations(expected, observed)
    assert all(a.passed for a in asserts)


def test_secret_scan_helper(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text('{"ok": true}', encoding="utf-8")
    (tmp_path / "leak.md").write_text("token ghp_SYNTHETICFAKETOKEN0001XX here", encoding="utf-8")
    leaked = scan_secrets_in_tree(tmp_path, ("ghp_SYNTHETICFAKETOKEN0001XX",))
    assert leaked == ("ghp_SYNTHETICFAKETOKEN0001XX",)


def test_report_generation(tmp_path: Path) -> None:
    results = [
        BenchmarkCaseResult(
            case_id="BENCH-X",
            passed=False,
            duration_ms=12.5,
            category="POLICY",
            failure_reason="policy_outcome",
            assertions=[
                BenchmarkAssertionResult(
                    "policy_outcome", False, "ESCALATE", "APPROVE"
                )
            ],
            run_id="run-1",
        )
    ]
    metrics = compute_suite_metrics(results)
    paths = write_reports(
        output_dir=tmp_path / "out",
        suite_run_id="bench-test",
        results=results,
        metrics=metrics,
        comparison=[],
    )
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert summary["failed"] == 1
    md = paths["report"].read_text(encoding="utf-8")
    assert "BENCH-X" in md
    assert "Benchmark Summary" in md
    assert "Metrics" in md


def test_reproducibility_classify() -> None:
    cases = filter_cases(load_suite(CASES_DIR), case_id="BENCH-CLASS-001")
    runner = BenchmarkRunner(benchmark_mode=True)
    a = runner.run_case(cases[0])
    b = runner.run_case(cases[0])
    assert a.passed and b.passed
    assert a.observed["classification"] == b.observed["classification"]
    assert a.assertions[0].passed == b.assertions[0].passed


def test_order_independence() -> None:
    cases = filter_cases(load_suite(CASES_DIR), category="CLASSIFICATION")
    runner = BenchmarkRunner(benchmark_mode=True)
    forward = {r.case_id: r.passed for r in [runner.run_case(c) for c in cases]}
    reverse = {
        r.case_id: r.passed for r in [runner.run_case(c) for c in reversed(cases)]
    }
    assert forward == reverse


def test_case_isolation(tmp_path: Path) -> None:
    """Workspace mutation in case 1 must not leak into case 2."""

    runner = BenchmarkRunner(benchmark_mode=True)
    cases = filter_cases(load_suite(CASES_DIR), case_id="BENCH-REPAIR-001")
    r1 = runner.run_case(cases[0])
    r2 = runner.run_case(cases[0])
    assert r1.passed and r2.passed
    assert r1.run_id != r2.run_id


def test_exit_code_semantics(tmp_path: Path) -> None:
    runner = BenchmarkRunner(
        cases_dir=CASES_DIR,
        artifacts_root=tmp_path / "arts",
        benchmark_mode=True,
    )
    suite = runner.run_suite(case_id="BENCH-CLASS-001", compare_baseline=False)
    assert suite.exit_code == 0
    assert suite.results[0].passed


def test_security_path_traversal_containment() -> None:
    runner = BenchmarkRunner(benchmark_mode=True)
    case = filter_cases(load_suite(CASES_DIR), case_id="BENCH-SEC-001")[0]
    result = runner.run_case(case)
    assert result.passed, result.failure_reason or result.harness_error
    assert result.observed.get("tool_blocked") is True


def test_unknown_tool_blocked() -> None:
    runner = BenchmarkRunner(benchmark_mode=True)
    case = filter_cases(load_suite(CASES_DIR), case_id="BENCH-SEC-002")[0]
    result = runner.run_case(case)
    assert result.passed, result.failure_reason or result.harness_error

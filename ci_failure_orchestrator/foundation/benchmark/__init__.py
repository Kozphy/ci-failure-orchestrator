"""Phase 12 — foundation benchmark harness (deterministic, synthetic).

Does not measure production LLM quality. Dataset is SYNTHETIC.
"""

from .baseline import BaselineStore, CaseDelta, compare_to_baseline
from .loader import load_case, load_suite
from .metrics import MetricResult, compute_suite_metrics
from .report import write_reports
from .runner import BenchmarkRunner, BenchmarkSuiteResult
from .schemas import (
    BENCHMARK_SCHEMA_VERSION,
    SUITE_VERSION,
    BenchmarkAssertionResult,
    BenchmarkCase,
    BenchmarkCaseResult,
    ExpectedResult,
)

__all__ = [
    "BENCHMARK_SCHEMA_VERSION",
    "SUITE_VERSION",
    "BaselineStore",
    "BenchmarkAssertionResult",
    "BenchmarkCase",
    "BenchmarkCaseResult",
    "BenchmarkRunner",
    "BenchmarkSuiteResult",
    "CaseDelta",
    "ExpectedResult",
    "MetricResult",
    "compare_to_baseline",
    "compute_suite_metrics",
    "load_case",
    "load_suite",
    "write_reports",
]

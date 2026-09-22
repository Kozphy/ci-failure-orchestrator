"""Denominator-aware benchmark metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schemas import BenchmarkCaseResult


@dataclass
class MetricResult:
    name: str
    numerator: int
    denominator: int
    value: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
            "display": (
                f"{self.numerator}/{self.denominator}"
                if self.denominator
                else "n/a (zero denominator)"
            ),
        }


def _ratio(num: int, den: int) -> float | None:
    if den == 0:
        return None
    return num / den


def _in_pop(result: BenchmarkCaseResult, name: str) -> bool:
    return name in result.populations


def case_pass_rate(results: list[BenchmarkCaseResult]) -> MetricResult:
    den = len(results)
    num = sum(1 for r in results if r.passed)
    return MetricResult("case_pass_rate", num, den, _ratio(num, den))


def required_pass_rate(results: list[BenchmarkCaseResult]) -> MetricResult:
    subset = [r for r in results if r.required]
    den = len(subset)
    num = sum(1 for r in subset if r.passed)
    return MetricResult("required_pass_rate", num, den, _ratio(num, den))


def classification_accuracy(results: list[BenchmarkCaseResult]) -> MetricResult:
    subset = [r for r in results if _in_pop(r, "classification")]
    den = len(subset)
    num = 0
    for r in subset:
        assertion = next((a for a in r.assertions if a.name == "classification"), None)
        if assertion and assertion.passed:
            num += 1
        elif assertion is None and r.passed:
            num += 1
    return MetricResult("classification_accuracy", num, den, _ratio(num, den))


def repair_success_rate(results: list[BenchmarkCaseResult]) -> MetricResult:
    """Repairable cases ending in technical PASS / repairable population."""

    subset = [r for r in results if _in_pop(r, "repairable")]
    den = len(subset)
    num = 0
    for r in subset:
        tech = r.observed.get("technical_status")
        if tech == "PASS":
            num += 1
    return MetricResult("repair_success_rate", num, den, _ratio(num, den))


def retry_rate(results: list[BenchmarkCaseResult]) -> MetricResult:
    subset = [r for r in results if _in_pop(r, "retry")]
    den = len(subset)
    num = sum(1 for r in subset if int(r.observed.get("retries") or 0) > 0)
    return MetricResult("retry_rate", num, den, _ratio(num, den))


def mean_attempts(results: list[BenchmarkCaseResult]) -> MetricResult:
    vals = [
        int(r.observed.get("attempts") or 0)
        for r in results
        if r.observed.get("attempts") is not None
    ]
    den = len(vals)
    total = sum(vals)
    return MetricResult(
        "mean_attempts",
        total,
        den,
        (total / den) if den else None,
    )


def policy_outcome_accuracy(results: list[BenchmarkCaseResult]) -> MetricResult:
    subset = [r for r in results if _in_pop(r, "policy")]
    den = len(subset)
    num = 0
    for r in subset:
        assertion = next((a for a in r.assertions if a.name == "policy_outcome"), None)
        if assertion and assertion.passed:
            num += 1
    return MetricResult("policy_outcome_accuracy", num, den, _ratio(num, den))


def security_control_success_rate(results: list[BenchmarkCaseResult]) -> MetricResult:
    subset = [r for r in results if _in_pop(r, "security")]
    den = len(subset)
    num = sum(1 for r in subset if r.passed)
    return MetricResult("security_control_success_rate", num, den, _ratio(num, den))


def escalation_accuracy(results: list[BenchmarkCaseResult]) -> MetricResult:
    subset = [r for r in results if _in_pop(r, "escalation")]
    den = len(subset)
    num = 0
    for r in subset:
        ok = True
        for name in ("policy_outcome", "escalation_required", "workflow_status"):
            assertion = next((a for a in r.assertions if a.name == name), None)
            if assertion is not None and not assertion.passed:
                ok = False
        if ok and r.passed:
            num += 1
        elif ok and all(
            next((a for a in r.assertions if a.name == n), None) is None
            or next(a for a in r.assertions if a.name == n).passed
            for n in ("policy_outcome", "escalation_required")
            if any(a.name == n for a in r.assertions)
        ):
            # count assertion-level correctness even if other assertions failed
            pol = next((a for a in r.assertions if a.name == "policy_outcome"), None)
            esc = next((a for a in r.assertions if a.name == "escalation_required"), None)
            if (pol is None or pol.passed) and (esc is None or esc.passed):
                if pol is not None or esc is not None:
                    num += 1
    # Simplify: case passed within escalation population
    num = sum(1 for r in subset if r.passed)
    return MetricResult("escalation_accuracy", num, den, _ratio(num, den))


def audit_completeness_rate(results: list[BenchmarkCaseResult]) -> MetricResult:
    subset = [r for r in results if _in_pop(r, "audit")]
    den = len(subset)
    num = 0
    for r in subset:
        assertion = next((a for a in r.assertions if a.name == "audit_completeness"), None)
        if assertion and assertion.passed:
            num += 1
        elif assertion is None and r.observed.get("audit_complete") is True:
            num += 1
    return MetricResult("audit_completeness_rate", num, den, _ratio(num, den))


def false_remediation_count(results: list[BenchmarkCaseResult]) -> MetricResult:
    """Technical PASS that violates golden governance/functional expectations."""

    count = 0
    for r in results:
        if r.observed.get("technical_status") != "PASS":
            continue
        if not r.passed:
            # technical success but case failed golden expectations
            count += 1
    return MetricResult("false_remediation_count", count, len(results), float(count))


def policy_confusion(results: list[BenchmarkCaseResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        if not _in_pop(r, "policy"):
            continue
        assertion = next((a for a in r.assertions if a.name == "policy_outcome"), None)
        if assertion is None:
            continue
        key = f"expected {assertion.expected} → actual {assertion.actual}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def classification_confusion(results: list[BenchmarkCaseResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        if not _in_pop(r, "classification"):
            continue
        assertion = next((a for a in r.assertions if a.name == "classification"), None)
        if assertion is None:
            continue
        key = f"expected {assertion.expected} → actual {assertion.actual}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def failure_taxonomy_coverage(results: list[BenchmarkCaseResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        cat = r.observed.get("classification")
        if cat:
            counts[str(cat)] = counts.get(str(cat), 0) + 1
    return counts


def policy_outcome_coverage(results: list[BenchmarkCaseResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        outcome = r.observed.get("policy_outcome")
        if outcome:
            counts[str(outcome)] = counts.get(str(outcome), 0) + 1
    return counts


def retry_stop_reason_counts(results: list[BenchmarkCaseResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        reason = r.observed.get("stop_reason")
        if reason:
            counts[str(reason)] = counts.get(str(reason), 0) + 1
    return counts


def compute_suite_metrics(results: list[BenchmarkCaseResult]) -> dict[str, Any]:
    metrics = [
        case_pass_rate(results),
        required_pass_rate(results),
        classification_accuracy(results),
        repair_success_rate(results),
        retry_rate(results),
        mean_attempts(results),
        policy_outcome_accuracy(results),
        security_control_success_rate(results),
        escalation_accuracy(results),
        audit_completeness_rate(results),
        false_remediation_count(results),
    ]
    durations = [r.duration_ms for r in results]
    return {
        "metrics": {m.name: m.to_dict() for m in metrics},
        "policy_confusion": policy_confusion(results),
        "classification_confusion": classification_confusion(results),
        "failure_taxonomy_coverage": failure_taxonomy_coverage(results),
        "policy_outcome_coverage": policy_outcome_coverage(results),
        "retry_stop_reason_counts": retry_stop_reason_counts(results),
        "timing": {
            "note": "local benchmark timing only — not production latency",
            "suite_duration_ms": sum(durations),
            "mean_case_duration_ms": (sum(durations) / len(durations)) if durations else None,
            "model_cost": "NOT_APPLICABLE",
        },
    }

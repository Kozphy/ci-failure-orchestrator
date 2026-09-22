"""JSON + Markdown benchmark reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .baseline import CaseDelta, RegressionLabel
from .schemas import BENCHMARK_SCHEMA_VERSION, SUITE_VERSION, BenchmarkCaseResult


def write_reports(
    *,
    output_dir: Path,
    suite_run_id: str,
    results: list[BenchmarkCaseResult],
    metrics: dict[str, Any],
    comparison: list[CaseDelta] | None = None,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = output_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    passed = sum(1 for r in results if r.passed)
    failed = [r for r in results if not r.passed]
    required = [r for r in results if r.required]
    required_passed = sum(1 for r in required if r.passed)
    optional = [r for r in results if not r.required]
    optional_passed = sum(1 for r in optional if r.passed)

    summary = {
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "suite_version": SUITE_VERSION,
        "suite_run_id": suite_run_id,
        "synthetic": True,
        "model_cost": "NOT_APPLICABLE",
        "cases": len(results),
        "passed": passed,
        "failed": len(failed),
        "required_passed": required_passed,
        "required_total": len(required),
        "optional_passed": optional_passed,
        "optional_total": len(optional),
        "metrics": metrics,
        "case_results": [r.to_dict() for r in results],
        "comparison": [d.to_dict() for d in (comparison or [])],
    }

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    for r in results:
        (cases_dir / f"{r.case_id}.json").write_text(
            json.dumps(r.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    comparison_path = output_dir / "comparison.json"
    comparison_path.write_text(
        json.dumps([d.to_dict() for d in (comparison or [])], indent=2) + "\n",
        encoding="utf-8",
    )

    report_md = render_markdown(summary, results, comparison or [])
    report_path = output_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")

    return {
        "summary": summary_path,
        "report": report_path,
        "comparison": comparison_path,
    }


def render_markdown(
    summary: dict[str, Any],
    results: list[BenchmarkCaseResult],
    comparison: list[CaseDelta],
) -> str:
    lines: list[str] = []
    lines.append("# Benchmark Summary")
    lines.append("")
    lines.append("## Suite")
    lines.append("")
    lines.append(f"- Schema: `{summary.get('benchmark_schema_version')}`")
    lines.append(f"- Suite version: `{summary.get('suite_version')}`")
    lines.append(f"- Suite run ID: `{summary.get('suite_run_id')}`")
    lines.append("- Dataset: **SYNTHETIC** (not production distribution)")
    lines.append(f"- Model cost: `{summary.get('model_cost')}`")
    lines.append("")
    lines.append("## Overall Result")
    lines.append("")
    lines.append(
        f"- Cases: {summary['cases']} | Passed: {summary['passed']} | Failed: {summary['failed']}"
    )
    lines.append(
        f"- Required: {summary['required_passed']}/{summary['required_total']}"
    )
    lines.append(
        f"- Optional: {summary['optional_passed']}/{summary['optional_total']}"
    )
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Result |")
    lines.append("| --- | --- |")
    metric_block = (summary.get("metrics") or {}).get("metrics") or {}
    for name, info in metric_block.items():
        if isinstance(info, dict):
            lines.append(f"| {name} | {info.get('display', info.get('value'))} |")
    lines.append("")
    lines.append(
        "_Percentages use explicit numerators/denominators; small samples are not "
        "statistically representative._"
    )
    lines.append("")

    lines.append("## Regressions")
    lines.append("")
    regressed = [d for d in comparison if d.label is RegressionLabel.REGRESSED]
    improved = [d for d in comparison if d.label is RegressionLabel.IMPROVED]
    if not comparison:
        lines.append("No baseline comparison.")
    else:
        lines.append(f"- REGRESSED: {len(regressed)}")
        lines.append(f"- IMPROVED: {len(improved)}")
        lines.append(
            f"- NEW_CASE: {sum(1 for d in comparison if d.label is RegressionLabel.NEW_CASE)}"
        )
        lines.append(
            f"- REMOVED_CASE: {sum(1 for d in comparison if d.label is RegressionLabel.REMOVED_CASE)}"
        )
        for d in regressed:
            lines.append(f"  - `{d.case_id}` pass→fail")
    lines.append("")

    lines.append("## Fixed Cases")
    lines.append("")
    if not improved:
        lines.append("None.")
    else:
        for d in improved:
            lines.append(f"- `{d.case_id}`")
    lines.append("")

    lines.append("## Failed Cases")
    lines.append("")
    failed = [r for r in results if not r.passed]
    if not failed:
        lines.append("None.")
    else:
        for r in failed:
            lines.append(f"### {r.case_id}")
            lines.append("")
            lines.append(f"- Run ID: `{r.run_id}`")
            if r.harness_error:
                lines.append(f"- Harness error: {r.harness_error}")
            if r.failure_reason:
                lines.append(f"- Failure: {r.failure_reason}")
            for a in r.assertions:
                if not a.passed:
                    lines.append(
                        f"- Failed assertion `{a.name}`: expected `{a.expected}` "
                        f"actual `{a.actual}`"
                    )
            lines.append("")
    lines.append("")

    def _section(title: str, category: str) -> None:
        lines.append(f"## {title}")
        lines.append("")
        subset = [r for r in results if r.category == category or category.lower() in r.tags]
        if not subset:
            lines.append("No cases.")
        else:
            for r in subset:
                mark = "PASS" if r.passed else "FAIL"
                lines.append(f"- `{r.case_id}` — {mark}")
        lines.append("")

    _section("Security Cases", "SECURITY")
    _section("Policy Cases", "POLICY")
    _section("Retry Cases", "RETRY")

    lines.append("## Case Details")
    lines.append("")
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        lines.append(
            f"- `{r.case_id}` [{r.category}] {mark} "
            f"({r.duration_ms:.1f} ms) run=`{r.run_id}`"
        )
    lines.append("")
    return "\n".join(lines)

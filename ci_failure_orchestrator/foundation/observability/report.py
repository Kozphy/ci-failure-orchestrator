"""Operational JSON + Markdown reports (distinct from Phase 12 benchmark reports)."""

from __future__ import annotations

import json
from pathlib import Path

from .aggregator import OperationalSnapshot
from .slo import SLOStatus


def write_operations_report(
    snapshot: OperationalSnapshot,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = output_dir / "metrics.json"
    sli_path = output_dir / "sli-report.json"
    slo_path = output_dir / "slo-report.json"
    md_path = output_dir / "operations-report.md"

    full = snapshot.to_dict()
    metrics_path.write_text(
        json.dumps(
            {
                "schema_version": snapshot.schema_version,
                "population": snapshot.population,
                "counters": snapshot.counters,
                "latency": full.get("latency"),
                "attempts": full.get("attempts"),
                "policy_outcomes": snapshot.policy_outcomes,
                "workflow_statuses": snapshot.workflow_statuses,
                "stop_reasons": snapshot.stop_reasons,
                "cost_metrics": "NOT_IMPLEMENTED",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    sli_path.write_text(
        json.dumps({"slis": [s.to_dict() for s in snapshot.slis]}, indent=2) + "\n",
        encoding="utf-8",
    )
    slo_path.write_text(
        json.dumps(
            {
                "slos": [s.to_dict() for s in snapshot.slos],
                "note": "Targets are EXAMPLE_TARGET / provisional unless marked otherwise",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_operations_markdown(snapshot), encoding="utf-8")
    return {
        "metrics": metrics_path,
        "sli": sli_path,
        "slo": slo_path,
        "report": md_path,
    }


def render_operations_markdown(snapshot: OperationalSnapshot) -> str:
    lines: list[str] = []
    lines.append("# Operational Observability Report")
    lines.append("")
    lines.append("## Population")
    lines.append("")
    lines.append(snapshot.population)
    lines.append(f"Window: `{snapshot.window}`")
    lines.append("")
    lines.append(
        "_These figures describe the retained local run population only. "
        "They are not production reliability claims._"
    )
    lines.append("")
    lines.append("## Run Outcomes")
    lines.append("")
    lines.append(f"- Runs: {snapshot.run_count}")
    for status, count in sorted(snapshot.workflow_statuses.items()):
        lines.append(f"- workflow `{status}`: {count}")
    lines.append("")
    lines.append("## Latency")
    lines.append("")
    if snapshot.latency and snapshot.latency.count:
        lat = snapshot.latency
        lines.append(
            f"- count={lat.count} min={lat.min} median={lat.median} "
            f"p95={lat.p95} max={lat.max} (seconds; local timing only)"
        )
    else:
        lines.append("- No duration observations.")
    lines.append("")
    lines.append("## Retry Behavior")
    lines.append("")
    if snapshot.attempts:
        lines.append(f"- attempts distribution: {snapshot.attempts.to_dict()}")
    for reason, count in sorted(snapshot.stop_reasons.items()):
        lines.append(f"- stop `{reason}`: {count}")
    lines.append("")
    lines.append("## Tool Reliability")
    lines.append("")
    lines.append("- See counters for `orchestrator_tool_calls_total` in metrics.json")
    lines.append("")
    lines.append("## Sandbox Reliability")
    lines.append("")
    lines.append("- See counters for sandbox_* metrics in metrics.json")
    lines.append("")
    lines.append("## Policy Outcomes")
    lines.append("")
    lines.append(
        "_Runtime policy outcome **distribution** — not Phase 12 policy accuracy._"
    )
    for outcome, count in sorted(snapshot.policy_outcomes.items()):
        lines.append(f"- `{outcome}`: {count}")
    lines.append("")
    lines.append("## Security Controls")
    lines.append("")
    lines.append("- See `orchestrator_security_*` counters (containment after detection)")
    lines.append("")
    lines.append("## Audit Completeness")
    lines.append("")
    audit = next((s for s in snapshot.slis if s.sli_id == "SLI-008"), None)
    if audit:
        lines.append(f"- {audit.to_dict()['display']}")
    lines.append("")
    lines.append("## Persistence Reliability")
    lines.append("")
    pers = next((s for s in snapshot.slis if s.sli_id == "SLI-009"), None)
    if pers:
        lines.append(f"- {pers.to_dict()['display']}")
    lines.append("")
    lines.append("## SLIs")
    lines.append("")
    lines.append("| SLI | Result |")
    lines.append("| --- | --- |")
    for s in snapshot.slis:
        lines.append(f"| {s.sli_id} {s.name} | {s.to_dict()['display']} |")
    lines.append("")
    lines.append("## SLO Status")
    lines.append("")
    lines.append("_All targets below are **EXAMPLE_TARGET** / provisional._")
    lines.append("")
    for s in snapshot.slos:
        lines.append(
            f"- `{s.slo_id}` ({s.sli_id}): **{s.status.value}** "
            f"observed={s.observed_value} target={s.target} "
            f"({s.numerator}/{s.denominator})"
        )
    lines.append("")
    lines.append("## Insufficient Data")
    lines.append("")
    insuf = [s for s in snapshot.slos if s.status is SLOStatus.INSUFFICIENT_DATA]
    if not insuf:
        lines.append("None.")
    else:
        for s in insuf:
            lines.append(f"- `{s.slo_id}`: {s.detail}")
    lines.append("")
    if snapshot.consistency_issues:
        lines.append("## Consistency Issues")
        lines.append("")
        for issue in snapshot.consistency_issues:
            lines.append(f"- `{issue.run_id}`: {issue.message}")
        lines.append("")
    lines.append("## Known Limitations")
    lines.append("")
    for lim in snapshot.limitations:
        lines.append(f"- {lim}")
    lines.append("")
    return "\n".join(lines)

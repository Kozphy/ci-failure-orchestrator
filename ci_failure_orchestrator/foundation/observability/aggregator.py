"""Rebuild operational metrics from durable run artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..persistence import FileStateStore
from .audit_check import check_audit_artifacts
from .metrics import OBSERVABILITY_SCHEMA, InMemoryMetricsRecorder
from .sli import SLIResult, compute_slis
from .slo import SLODefinition, SLOResult, default_slo_definitions, evaluate_slos, load_slo_config
from .stats import DistributionSummary, summarize_distribution
from .summary import RunMetricsSummary


@dataclass
class ConsistencyIssue:
    run_id: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"run_id": self.run_id, "message": self.message}


@dataclass
class OperationalSnapshot:
    schema_version: str
    population: str
    source_filter: str
    run_count: int
    generated_at: str
    summaries: list[RunMetricsSummary] = field(default_factory=list)
    counters: dict[str, Any] = field(default_factory=dict)
    latency: DistributionSummary | None = None
    attempts: DistributionSummary | None = None
    policy_outcomes: dict[str, int] = field(default_factory=dict)
    workflow_statuses: dict[str, int] = field(default_factory=dict)
    stop_reasons: dict[str, int] = field(default_factory=dict)
    slis: list[SLIResult] = field(default_factory=list)
    slos: list[SLOResult] = field(default_factory=list)
    consistency_issues: list[ConsistencyIssue] = field(default_factory=list)
    window: str = "retained_local_runs"
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "population": self.population,
            "source_filter": self.source_filter,
            "run_count": self.run_count,
            "generated_at": self.generated_at,
            "window": self.window,
            "counters": self.counters,
            "latency": self.latency.to_dict() if self.latency else None,
            "attempts": self.attempts.to_dict() if self.attempts else None,
            "policy_outcomes": self.policy_outcomes,
            "workflow_statuses": self.workflow_statuses,
            "stop_reasons": self.stop_reasons,
            "slis": [s.to_dict() for s in self.slis],
            "slos": [s.to_dict() for s in self.slos],
            "consistency_issues": [c.to_dict() for c in self.consistency_issues],
            "limitations": self.limitations,
            "summaries": [s.to_dict() for s in self.summaries],
            "cost_metrics": "NOT_IMPLEMENTED",
            "model_cost": "NOT_APPLICABLE",
        }


def load_run_summaries(
    artifacts_root: Path,
    *,
    source: str = "runtime",
    limit: int | None = None,
) -> list[RunMetricsSummary]:
    """Load RunMetricsSummary from metrics-summary.json or derive from state.json."""

    root = Path(artifacts_root) / "runs"
    if not root.is_dir():
        return []
    run_dirs = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name)
    if limit is not None:
        run_dirs = run_dirs[-limit:]
    out: list[RunMetricsSummary] = []
    store = FileStateStore(artifacts_root)
    for run_dir in run_dirs:
        summary_path = run_dir / "metrics-summary.json"
        if summary_path.is_file():
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            summary = RunMetricsSummary.from_dict(data)
            if source and summary.source != source:
                continue
            out.append(summary)
            continue
        # Derive from durable state
        run_id = run_dir.name
        try:
            state = store.load_run(run_id)
        except Exception:  # noqa: BLE001
            continue
        audit_complete = None
        if (run_dir / "state.json").is_file():
            ok, _ = check_audit_artifacts(run_dir)
            audit_complete = ok
        attempts = int(state.current_attempt or 0)
        summary = RunMetricsSummary(
            schema_version=OBSERVABILITY_SCHEMA,
            run_id=run_id,
            source="runtime",
            technical_status=state.technical_status,
            workflow_status=state.workflow_status,
            policy_outcome=state.policy_outcome,
            failure_category=None,
            attempts=attempts,
            retries=max(0, attempts - 1) if attempts else 0,
            stop_reason=state.stop_reason,
            duration_seconds=None,
            tool_calls=0,
            tool_failures=0,
            sandbox_runs=0,
            sandbox_failures=0,
            evaluations=1 if state.latest_evaluation_ref else 0,
            evaluation_failures=0,
            security_findings=0,
            security_blocks=0,
            secret_redactions=0,
            escalated=state.workflow_status == "AWAITING_HUMAN",
            evidence_status=None,
            audit_complete=audit_complete,
            persistence_ok=state.workflow_status != "PERSISTENCE_ERROR",
            eligible_repair=True,
        )
        if source and summary.source != source:
            continue
        out.append(summary)
    return out


def build_metrics_from_runs(
    artifacts_root: Path,
    *,
    source: str = "runtime",
    limit: int | None = None,
) -> tuple[list[RunMetricsSummary], InMemoryMetricsRecorder, list[ConsistencyIssue]]:
    summaries = load_run_summaries(artifacts_root, source=source, limit=limit)
    recorder = InMemoryMetricsRecorder()
    issues: list[ConsistencyIssue] = []
    for s in summaries:
        if s.attempts < 0 or (s.retries > 0 and s.attempts < s.retries + 1):
            issues.append(
                ConsistencyIssue(
                    s.run_id,
                    f"attempt/retry inconsistency attempts={s.attempts} retries={s.retries}",
                )
            )
        if s.technical_status == "PASS" and s.policy_outcome is None:
            issues.append(
                ConsistencyIssue(s.run_id, "technical PASS without policy_outcome")
            )
        # Re-emit derived counters (rebuildable)
        recorder.increment(
            "orchestrator_runs_total",
            labels={
                "technical_status": s.technical_status or "unknown",
                "workflow_status": s.workflow_status or "unknown",
                "source": s.source,
            },
        )
        if s.technical_status == "PASS":
            recorder.increment("orchestrator_runs_succeeded_total", labels={"source": s.source})
        else:
            recorder.increment("orchestrator_runs_failed_total", labels={"source": s.source})
        if s.policy_outcome == "APPROVE":
            recorder.increment("orchestrator_runs_approved_total", labels={"source": s.source})
        elif s.policy_outcome == "REJECT":
            recorder.increment("orchestrator_runs_rejected_total", labels={"source": s.source})
        elif s.policy_outcome == "ESCALATE":
            recorder.increment("orchestrator_runs_escalated_total", labels={"source": s.source})
        if s.duration_seconds is not None:
            recorder.observe(
                "orchestrator_run_duration_seconds",
                s.duration_seconds,
                labels={"workflow_status": s.workflow_status or "unknown", "source": s.source},
            )
        recorder.increment(
            "orchestrator_attempts_total",
            value=s.attempts,
            labels={"source": s.source},
        )
        if s.retries > 0:
            recorder.increment(
                "orchestrator_retries_total",
                value=s.retries,
                labels={"source": s.source},
            )
            recorder.increment(
                "orchestrator_runs_with_retry_total",
                labels={"source": s.source},
            )
        if s.policy_outcome:
            recorder.increment(
                "orchestrator_policy_decisions_total",
                labels={"policy_outcome": s.policy_outcome, "source": s.source},
            )
        if s.security_findings:
            recorder.increment(
                "orchestrator_security_findings_total",
                value=s.security_findings,
                labels={"security_category": "derived", "source": s.source},
            )
        if s.security_blocks:
            recorder.increment(
                "orchestrator_security_blocks_total",
                value=s.security_blocks,
                labels={"security_category": "derived", "source": s.source},
            )
        if s.audit_complete is True:
            recorder.increment("orchestrator_audit_complete_total", labels={"source": s.source})
        elif s.audit_complete is False:
            recorder.increment(
                "orchestrator_audit_incomplete_total", labels={"source": s.source}
            )
    return summaries, recorder, issues


def build_snapshot(
    artifacts_root: Path,
    *,
    source: str = "runtime",
    limit: int | None = None,
    slo_config: Path | None = None,
) -> OperationalSnapshot:
    summaries, recorder, issues = build_metrics_from_runs(
        artifacts_root, source=source, limit=limit
    )
    durations = [s.duration_seconds for s in summaries if s.duration_seconds is not None]
    attempts = [float(s.attempts) for s in summaries if s.attempts is not None]
    policy_outcomes: dict[str, int] = {}
    workflows: dict[str, int] = {}
    stops: dict[str, int] = {}
    for s in summaries:
        if s.policy_outcome:
            policy_outcomes[s.policy_outcome] = policy_outcomes.get(s.policy_outcome, 0) + 1
        if s.workflow_status:
            workflows[s.workflow_status] = workflows.get(s.workflow_status, 0) + 1
        if s.stop_reason:
            stops[s.stop_reason] = stops.get(s.stop_reason, 0) + 1

    slis = compute_slis(summaries)
    definitions = load_slo_config(slo_config) if slo_config else default_slo_definitions()
    slo_results = evaluate_slos(definitions, slis)

    pop = (
        f"{len(summaries)} retained local runs "
        f"(source={source}, artifacts={Path(artifacts_root).as_posix()})"
    )
    return OperationalSnapshot(
        schema_version=OBSERVABILITY_SCHEMA,
        population=pop,
        source_filter=source,
        run_count=len(summaries),
        generated_at=datetime.now(timezone.utc).isoformat(),
        summaries=summaries,
        counters=recorder.snapshot().get("counters", {}),
        latency=summarize_distribution(durations),
        attempts=summarize_distribution(attempts),
        policy_outcomes=policy_outcomes,
        workflow_statuses=workflows,
        stop_reasons=stops,
        slis=slis,
        slos=slo_results,
        consistency_issues=issues,
        window="retained_local_runs" + (f":last_{limit}" if limit else ""),
        limitations=[
            "Local metrics backend only — not a production monitoring platform",
            "Retained artifact population may be incomplete; deleting runs changes history",
            "Provisional EXAMPLE SLO targets are not measured production SLOs",
            "Phase 12 benchmark accuracy metrics are a separate population",
            "No deployed dashboard or external alerts",
            "cost metrics not implemented",
        ],
    )

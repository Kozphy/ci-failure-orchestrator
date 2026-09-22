"""Per-run metrics summary (run_id allowed here — not as a metric label)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .metrics import OBSERVABILITY_SCHEMA

if TYPE_CHECKING:
    from ..runner import FoundationResult


_TERMINAL_AUTOMATION = frozenset(
    {
        "APPROVED",
        "REJECTED",
        "FAILED",
        "SUCCEEDED",
        "AWAITING_HUMAN",
        "ESCALATION_ERROR",
        "PERSISTENCE_ERROR",
    }
)


@dataclass
class RunMetricsSummary:
    """Persisted per-run observability summary. May include run_id; never secrets."""

    schema_version: str
    run_id: str
    source: str  # runtime | benchmark
    technical_status: str | None
    workflow_status: str | None
    policy_outcome: str | None
    failure_category: str | None
    attempts: int
    retries: int
    stop_reason: str | None
    duration_seconds: float | None
    tool_calls: int
    tool_failures: int
    sandbox_runs: int
    sandbox_failures: int
    evaluations: int
    evaluation_failures: int
    security_findings: int
    security_blocks: int
    secret_redactions: int
    escalated: bool
    evidence_status: str | None  # COMPLETE | PARTIAL | INCOMPLETE | None
    audit_complete: bool | None
    persistence_ok: bool
    eligible_repair: bool
    labels: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunMetricsSummary:
        return cls(
            schema_version=str(data.get("schema_version") or OBSERVABILITY_SCHEMA),
            run_id=str(data.get("run_id") or ""),
            source=str(data.get("source") or "runtime"),
            technical_status=data.get("technical_status"),
            workflow_status=data.get("workflow_status"),
            policy_outcome=data.get("policy_outcome"),
            failure_category=data.get("failure_category"),
            attempts=int(data.get("attempts") or 0),
            retries=int(data.get("retries") or 0),
            stop_reason=data.get("stop_reason"),
            duration_seconds=(
                float(data["duration_seconds"])
                if data.get("duration_seconds") is not None
                else None
            ),
            tool_calls=int(data.get("tool_calls") or 0),
            tool_failures=int(data.get("tool_failures") or 0),
            sandbox_runs=int(data.get("sandbox_runs") or 0),
            sandbox_failures=int(data.get("sandbox_failures") or 0),
            evaluations=int(data.get("evaluations") or 0),
            evaluation_failures=int(data.get("evaluation_failures") or 0),
            security_findings=int(data.get("security_findings") or 0),
            security_blocks=int(data.get("security_blocks") or 0),
            secret_redactions=int(data.get("secret_redactions") or 0),
            escalated=bool(data.get("escalated")),
            evidence_status=data.get("evidence_status"),
            audit_complete=data.get("audit_complete"),
            persistence_ok=bool(data.get("persistence_ok", True)),
            eligible_repair=bool(data.get("eligible_repair", True)),
            labels=dict(data.get("labels") or {}),
        )


def summarize_foundation_result(
    result: FoundationResult,
    *,
    duration_seconds: float | None = None,
    source: str = "runtime",
    audit_complete: bool | None = None,
    security_findings: int = 0,
    security_blocks: int = 0,
    secret_redactions: int = 0,
    persistence_ok: bool = True,
    tool_calls: int | None = None,
    tool_failures: int = 0,
    sandbox_runs: int | None = None,
    sandbox_failures: int = 0,
    evaluations: int | None = None,
    evaluation_failures: int = 0,
) -> RunMetricsSummary:
    from ..models import RunStatus
    from ..policy import PolicyOutcome

    run = result.run
    category = run.classification.category if run.classification else None
    tools = 0
    if run.plan is not None:
        tools = len(run.plan.steps) or len(run.plan.required_tools)
    if tool_calls is not None:
        tools = tool_calls
    sandbox_n = 1 if run.sandbox is not None else 0
    if sandbox_runs is not None:
        sandbox_n = sandbox_runs
    sandbox_fail = 0
    if run.sandbox is not None and not run.sandbox.success:
        sandbox_fail = 1
    sandbox_fail = max(sandbox_fail, sandbox_failures)
    eval_n = 1 if run.evaluation is not None else (evaluations or 0)
    if evaluations is not None:
        eval_n = evaluations
    eval_fail = evaluation_failures
    if run.evaluation is not None and not run.evaluation.passed:
        eval_fail = max(eval_fail, 1)

    evidence_status = None
    if result.escalation is not None:
        evidence_status = result.escalation.evidence_completeness.status.value

    workflow = result.workflow_status or result.status.value
    policy = (
        result.policy_outcome.value
        if result.policy_outcome is not None
        else run.policy_outcome
    )
    # Eligible repair: exclude intentional containment / security-boundary stops
    eligible = True
    if result.stop_reason and result.stop_reason.value in {
        "SECURITY_BOUNDARY_HIT",
        "INVALID_PROPOSAL",
    }:
        eligible = False
    if run.evaluation and run.evaluation.forbidden_changes_detected:
        eligible = False

    return RunMetricsSummary(
        schema_version=OBSERVABILITY_SCHEMA,
        run_id=run.run_id,
        source=source if source in {"runtime", "benchmark"} else "runtime",
        technical_status=result.technical_status or run.technical_status,
        workflow_status=workflow,
        policy_outcome=policy,
        failure_category=category,
        attempts=result.attempts,
        retries=result.retries,
        stop_reason=result.stop_reason.value if result.stop_reason else run.stop_reason,
        duration_seconds=duration_seconds,
        tool_calls=tools,
        tool_failures=tool_failures,
        sandbox_runs=sandbox_n,
        sandbox_failures=sandbox_fail,
        evaluations=eval_n,
        evaluation_failures=eval_fail,
        security_findings=security_findings,
        security_blocks=security_blocks,
        secret_redactions=secret_redactions,
        escalated=policy == PolicyOutcome.ESCALATE.value
        or workflow == RunStatus.AWAITING_HUMAN.value,
        evidence_status=evidence_status,
        audit_complete=audit_complete,
        persistence_ok=persistence_ok,
        eligible_repair=eligible,
    )


def write_run_metrics_summary(artifacts_root: Path, summary: RunMetricsSummary) -> Path:
    root = Path(artifacts_root) / "runs" / summary.run_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / "metrics-summary.json"
    path.write_text(json.dumps(summary.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def is_terminal_automation(workflow_status: str | None) -> bool:
    return bool(workflow_status and workflow_status in _TERMINAL_AUTOMATION)

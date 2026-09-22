"""Emit foundation run metrics through MetricsRecorder."""

from __future__ import annotations

from pathlib import Path

from ..models import RunStatus
from ..policy import PolicyOutcome
from ..retry import RetryReason
from ..runner import FoundationResult
from .audit_check import check_audit_artifacts
from .metrics import MetricsRecorder
from .summary import (
    summarize_foundation_result,
    write_run_metrics_summary,
)


def record_foundation_run(
    metrics: MetricsRecorder,
    result: FoundationResult,
    *,
    duration_seconds: float | None = None,
    source: str = "runtime",
    artifacts_root: Path | None = None,
    persist_summary: bool = True,
) -> None:
    """Record counters/observations for a completed foundation run.

    Telemetry failures must be absorbed by SafeMetricsRecorder wrapper.
    """

    run = result.run
    workflow = result.workflow_status or result.status.value
    technical = result.technical_status or run.technical_status or "FAIL"
    policy = (
        result.policy_outcome.value
        if result.policy_outcome is not None
        else (run.policy_outcome or "none")
    )
    category = (
        run.classification.category if run.classification else "unknown"
    )
    stop = (
        result.stop_reason.value
        if result.stop_reason is not None
        else (run.stop_reason or "unknown")
    )
    src = source if source in {"runtime", "benchmark"} else "runtime"

    # Audit completeness
    audit_complete = None
    if artifacts_root is not None:
        run_root = Path(artifacts_root) / "runs" / run.run_id
        if run_root.exists():
            audit_complete, _ = check_audit_artifacts(run_root)

    # Security signals derived from known control-plane outcomes
    security_findings = 0
    security_blocks = 0
    if result.stop_reason in {
        RetryReason.SECURITY_BOUNDARY_HIT,
        RetryReason.UNRECOVERABLE_FAILURE,
        RetryReason.INVALID_PROPOSAL,
    }:
        security_findings += 1
        security_blocks += 1
        metrics.increment(
            "orchestrator_security_findings_total",
            labels={
                "security_category": "forbidden_or_boundary",
                "action": "block",
                "source": src,
            },
        )
        metrics.increment(
            "orchestrator_security_blocks_total",
            labels={"security_category": "forbidden_or_boundary", "source": src},
        )
    if run.evaluation and run.evaluation.forbidden_changes_detected:
        security_findings += 1
        security_blocks += 1
        metrics.increment(
            "orchestrator_security_findings_total",
            labels={
                "security_category": "forbidden_change",
                "action": "block",
                "source": src,
            },
        )
        metrics.increment(
            "orchestrator_security_blocks_total",
            labels={"security_category": "forbidden_change", "source": src},
        )
    secret_redactions = 0
    if run.context and run.context.redactions_applied > 0:
        secret_redactions = int(run.context.redactions_applied)
        metrics.increment(
            "orchestrator_secret_redactions_total",
            value=secret_redactions,
            labels={"category": "sanitizer", "source": src},
        )

    summary = summarize_foundation_result(
        result,
        duration_seconds=duration_seconds,
        source=src,
        audit_complete=audit_complete,
        security_findings=security_findings,
        security_blocks=security_blocks,
        secret_redactions=secret_redactions,
        persistence_ok=workflow != "PERSISTENCE_ERROR",
    )

    metrics.increment(
        "orchestrator_runs_total",
        labels={
            "technical_status": technical,
            "workflow_status": workflow,
            "source": src,
        },
    )
    if technical == "PASS":
        metrics.increment(
            "orchestrator_runs_succeeded_total",
            labels={"source": src, "failure_category": category or "unknown"},
        )
    else:
        metrics.increment(
            "orchestrator_runs_failed_total",
            labels={"source": src, "failure_category": category or "unknown"},
        )

    if policy == PolicyOutcome.APPROVE.value:
        metrics.increment(
            "orchestrator_runs_approved_total",
            labels={"source": src},
        )
    elif policy == PolicyOutcome.REJECT.value:
        metrics.increment(
            "orchestrator_runs_rejected_total",
            labels={"source": src},
        )
    elif policy == PolicyOutcome.ESCALATE.value:
        metrics.increment(
            "orchestrator_runs_escalated_total",
            labels={"source": src},
        )

    if workflow == RunStatus.AWAITING_HUMAN.value:
        metrics.increment(
            "orchestrator_escalations_total",
            labels={"source": src, "evidence_status": summary.evidence_status or "unknown"},
        )

    if duration_seconds is not None:
        metrics.observe(
            "orchestrator_run_duration_seconds",
            duration_seconds,
            labels={"workflow_status": workflow, "source": src},
        )

    metrics.increment(
        "orchestrator_attempts_total",
        value=max(0, result.attempts),
        labels={"source": src},
    )
    if result.retries > 0:
        metrics.increment(
            "orchestrator_retries_total",
            value=result.retries,
            labels={"source": src},
        )
        metrics.increment(
            "orchestrator_runs_with_retry_total",
            labels={"source": src},
        )
    metrics.increment(
        "orchestrator_retry_stops_total",
        labels={"retry_stop_reason": stop, "source": src},
    )

    # Tools from plan steps
    if run.plan is not None:
        for step in run.plan.steps:
            metrics.increment(
                "orchestrator_tool_calls_total",
                labels={"tool_name": step.tool, "result": "success", "source": src},
            )

    if run.sandbox is not None:
        metrics.increment(
            "orchestrator_sandbox_runs_total",
            labels={"source": src},
        )
        if run.sandbox.success:
            metrics.increment(
                "orchestrator_sandbox_success_total",
                labels={"source": src},
            )
        else:
            metrics.increment(
                "orchestrator_sandbox_failures_total",
                labels={"source": src},
            )
            if run.sandbox.timeout:
                metrics.increment(
                    "orchestrator_sandbox_timeout_total",
                    labels={"source": src},
                )

    if run.evaluation is not None:
        metrics.increment(
            "orchestrator_evaluations_total",
            labels={"source": src},
        )
        if run.evaluation.passed:
            metrics.increment(
                "orchestrator_evaluation_pass_total",
                labels={"source": src},
            )
        else:
            metrics.increment(
                "orchestrator_evaluation_failures_total",
                labels={"source": src},
            )

    if result.policy_decision is not None:
        metrics.increment(
            "orchestrator_policy_decisions_total",
            labels={
                "policy_outcome": policy,
                "risk_level": result.policy_decision.risk_level.value,
                "source": src,
            },
        )
        for rule in result.policy_decision.matched_rules:
            # stable rule IDs only
            rid = str(rule)
            if len(rid) > 64:
                continue
            metrics.increment(
                "orchestrator_policy_rule_matches_total",
                labels={"rule_id": rid, "source": src},
            )

    if audit_complete is True:
        metrics.gauge(
            "orchestrator_audit_completeness",
            1.0,
            labels={"source": src},
        )
        metrics.increment(
            "orchestrator_audit_complete_total",
            labels={"source": src},
        )
    elif audit_complete is False:
        metrics.gauge(
            "orchestrator_audit_completeness",
            0.0,
            labels={"source": src},
        )
        metrics.increment(
            "orchestrator_audit_incomplete_total",
            labels={"source": src},
        )

    if persist_summary and artifacts_root is not None:
        try:
            write_run_metrics_summary(Path(artifacts_root), summary)
        except Exception:  # noqa: BLE001
            # summary write is telemetry — do not fail the run
            pass

"""Record recovery assessment metrics (bounded labels)."""

from __future__ import annotations

from ..persistence import RecoveryDecision
from .metrics import MetricsRecorder


def record_recovery_decision(
    metrics: MetricsRecorder,
    decision: RecoveryDecision,
    *,
    source: str = "runtime",
) -> None:
    src = source if source in {"runtime", "benchmark"} else "runtime"
    metrics.increment(
        "orchestrator_resume_attempts_total",
        labels={"resume_result": decision.status.value, "source": src},
    )
    status = decision.status.value
    if status == "RESUMABLE":
        metrics.increment(
            "orchestrator_resume_success_total",
            labels={"resume_result": status, "source": src},
        )
    elif status in {"REQUIRES_REVIEW", "TERMINAL", "INCONSISTENT"}:
        metrics.increment(
            "orchestrator_resume_blocked_total",
            labels={"resume_result": status, "source": src},
        )
    if status == "INCONSISTENT":
        metrics.increment(
            "orchestrator_consistency_failures_total",
            labels={"resume_result": status, "source": src},
        )

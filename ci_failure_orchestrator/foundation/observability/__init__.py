"""Phase 13 — foundation observability (metrics, SLI/SLO, operational reports).

Import submodules directly when needed to avoid circular imports with runner:

    from ci_failure_orchestrator.foundation.observability.metrics import InMemoryMetricsRecorder
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "InMemoryMetricsRecorder",
    "JsonMetricsRecorder",
    "MetricsRecorder",
    "NullMetricsRecorder",
    "SafeMetricsRecorder",
    "build_snapshot",
    "write_operations_report",
    "compute_slis",
    "evaluate_slos",
]


def __getattr__(name: str) -> Any:
    if name in {
        "InMemoryMetricsRecorder",
        "JsonMetricsRecorder",
        "MetricsRecorder",
        "NullMetricsRecorder",
        "SafeMetricsRecorder",
        "ALLOWED_LABEL_KEYS",
        "FORBIDDEN_LABEL_KEYS",
        "OBSERVABILITY_SCHEMA",
        "sanitize_labels",
    }:
        from . import metrics as _metrics

        return getattr(_metrics, name)
    if name in {"build_snapshot", "build_metrics_from_runs", "OperationalSnapshot"}:
        from . import aggregator as _agg

        return getattr(_agg, name)
    if name in {"write_operations_report"}:
        from . import report as _report

        return getattr(_report, name)
    if name in {"compute_slis", "SLIDefinition", "SLIResult"}:
        from . import sli as _sli

        return getattr(_sli, name)
    if name in {
        "SLODefinition",
        "SLOResult",
        "SLOStatus",
        "default_slo_definitions",
        "evaluate_error_budget",
        "evaluate_slo",
        "evaluate_slos",
        "load_slo_config",
    }:
        from . import slo as _slo

        return getattr(_slo, name)
    if name in {"RunMetricsSummary", "summarize_foundation_result"}:
        from . import summary as _summary

        return getattr(_summary, name)
    if name in {"record_foundation_run"}:
        from . import recorder as _rec

        return getattr(_rec, name)
    if name in {"DistributionSummary", "percentile", "summarize_distribution"}:
        from . import stats as _stats

        return getattr(_stats, name)
    raise AttributeError(name)

"""Backend-agnostic MetricsRecorder with cardinality controls."""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

OBSERVABILITY_SCHEMA = "foundation.observability.v1"

logger = logging.getLogger(__name__)

# Low-cardinality allowed label keys only.
ALLOWED_LABEL_KEYS: frozenset[str] = frozenset(
    {
        "status",
        "technical_status",
        "workflow_status",
        "failure_category",
        "tool_name",
        "result",
        "policy_outcome",
        "risk_level",
        "retry_stop_reason",
        "retry_reason",
        "security_category",
        "security_rule_id",
        "severity",
        "action",
        "rule_id",
        "check",
        "resume_result",
        "source",  # runtime | benchmark — bounded
        "category",
        "evidence_status",
    }
)

FORBIDDEN_LABEL_KEYS: frozenset[str] = frozenset(
    {
        "run_id",
        "commit_sha",
        "branch",
        "file_path",
        "exception_message",
        "patch",
        "user_input",
        "message",
        "log",
        "token",
        "secret",
    }
)


class MetricsRecorder(Protocol):
    def increment(
        self,
        metric: str,
        value: int = 1,
        labels: dict[str, str] | None = None,
    ) -> None: ...

    def observe(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None: ...

    def gauge(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None: ...


def sanitize_labels(labels: dict[str, str] | None) -> dict[str, str]:
    """Drop high-cardinality / forbidden keys; normalize unknown values."""

    if not labels:
        return {}
    out: dict[str, str] = {}
    for key, raw in labels.items():
        k = str(key)
        if k in FORBIDDEN_LABEL_KEYS or k not in ALLOWED_LABEL_KEYS:
            continue
        v = str(raw) if raw is not None else "unknown"
        if not v or len(v) > 64:
            v = "unknown"
        # reject values that look like UUIDs / paths / secrets
        if "/" in v or "\\" in v or " " in v:
            if k not in {"failure_category", "tool_name", "rule_id", "security_rule_id"}:
                v = "unknown"
        out[k] = v
    return out


def _label_key(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    return ",".join(f"{k}={labels[k]}" for k in sorted(labels))


@dataclass
class InMemoryMetricsRecorder:
    """Process-local counters / observations / gauges."""

    counters: dict[str, dict[str, float]] = field(default_factory=lambda: defaultdict(dict))
    observations: dict[str, dict[str, list[float]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list))
    )
    gauges: dict[str, dict[str, float]] = field(default_factory=lambda: defaultdict(dict))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def increment(
        self,
        metric: str,
        value: int = 1,
        labels: dict[str, str] | None = None,
    ) -> None:
        labels = sanitize_labels(labels)
        key = _label_key(labels)
        with self._lock:
            bucket = self.counters[metric]
            bucket[key] = bucket.get(key, 0.0) + float(value)

    def observe(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        labels = sanitize_labels(labels)
        key = _label_key(labels)
        with self._lock:
            self.observations[metric][key].append(float(value))

    def gauge(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        labels = sanitize_labels(labels)
        key = _label_key(labels)
        with self._lock:
            self.gauges[metric][key] = float(value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": OBSERVABILITY_SCHEMA,
                "counters": {
                    m: {k: v for k, v in buckets.items()}
                    for m, buckets in self.counters.items()
                },
                "observations": {
                    m: {k: list(vals) for k, vals in buckets.items()}
                    for m, buckets in self.observations.items()
                },
                "gauges": {
                    m: {k: v for k, v in buckets.items()}
                    for m, buckets in self.gauges.items()
                },
            }

    def counter_total(self, metric: str) -> float:
        with self._lock:
            return sum(self.counters.get(metric, {}).values())


@dataclass
class JsonMetricsRecorder:
    """Append-oriented JSONL metric emissions under artifacts/metrics/."""

    path: Path
    inner: InMemoryMetricsRecorder = field(default_factory=InMemoryMetricsRecorder)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, kind: str, metric: str, value: float, labels: dict[str, str]) -> None:
        record = {
            "schema_version": OBSERVABILITY_SCHEMA,
            "kind": kind,
            "metric": metric,
            "value": value,
            "labels": labels,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

    def increment(
        self,
        metric: str,
        value: int = 1,
        labels: dict[str, str] | None = None,
    ) -> None:
        clean = sanitize_labels(labels)
        self.inner.increment(metric, value, clean)
        self._append("counter", metric, float(value), clean)

    def observe(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        clean = sanitize_labels(labels)
        self.inner.observe(metric, value, clean)
        self._append("observation", metric, float(value), clean)

    def gauge(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        clean = sanitize_labels(labels)
        self.inner.gauge(metric, value, clean)
        self._append("gauge", metric, float(value), clean)

    def snapshot(self) -> dict[str, Any]:
        return self.inner.snapshot()


class NullMetricsRecorder:
    def increment(
        self,
        metric: str,
        value: int = 1,
        labels: dict[str, str] | None = None,
    ) -> None:
        return None

    def observe(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        return None

    def gauge(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        return None


class SafeMetricsRecorder:
    """Wraps a backend; never raises into the orchestrator."""

    def __init__(self, inner: MetricsRecorder) -> None:
        self._inner = inner
        self.failures = 0

    def increment(
        self,
        metric: str,
        value: int = 1,
        labels: dict[str, str] | None = None,
    ) -> None:
        try:
            self._inner.increment(metric, value, labels)
        except Exception as exc:  # noqa: BLE001
            self.failures += 1
            if self.failures <= 3:
                logger.warning("metrics increment failed: %s", type(exc).__name__)

    def observe(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        try:
            self._inner.observe(metric, value, labels)
        except Exception as exc:  # noqa: BLE001
            self.failures += 1
            if self.failures <= 3:
                logger.warning("metrics observe failed: %s", type(exc).__name__)

    def gauge(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        try:
            self._inner.gauge(metric, value, labels)
        except Exception as exc:  # noqa: BLE001
            self.failures += 1
            if self.failures <= 3:
                logger.warning("metrics gauge failed: %s", type(exc).__name__)

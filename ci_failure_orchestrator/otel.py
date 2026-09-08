"""Lightweight OpenTelemetry-compatible event bridge.

The core package remains dependency-light. This module emits structured span
records that can later be forwarded to a real OpenTelemetry SDK/exporter.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any, Callable
import uuid


@dataclass(frozen=True)
class SpanRecord:
    trace_id: str
    span_id: str
    name: str
    duration_ms: float
    status: str
    attributes: dict[str, Any] = field(default_factory=dict)


class SpanExporter:
    def __init__(self, sink: Callable[[dict[str, Any]], None] | None = None):
        self.sink = sink or (lambda _: None)

    def start(self, name: str, **attributes: Any):
        return _Span(self, name, attributes)

    def export(self, record: SpanRecord) -> None:
        self.sink(asdict(record))


class _Span:
    def __init__(self, exporter: SpanExporter, name: str, attributes: dict[str, Any]):
        self.exporter = exporter
        self.name = name
        self.attributes = attributes
        self.trace_id = uuid.uuid4().hex
        self.span_id = uuid.uuid4().hex[:16]
        self.started = 0.0
        self.status = "ok"

    def __enter__(self):
        self.started = perf_counter()
        return self

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.status = "error"
            self.attributes["exception.type"] = exc_type.__name__ if exc_type else "Exception"
        duration_ms = (perf_counter() - self.started) * 1000
        self.exporter.export(
            SpanRecord(
                trace_id=self.trace_id,
                span_id=self.span_id,
                name=self.name,
                duration_ms=duration_ms,
                status=self.status,
                attributes=dict(self.attributes),
            )
        )
        return False

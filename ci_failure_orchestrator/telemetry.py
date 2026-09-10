"""Telemetry primitives plus an optional OpenTelemetry production bridge."""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator, Mapping


@dataclass
class MetricsRegistry:
    """Small dependency-free registry used by local runs and unit tests."""

    counters: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    observations: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def inc(self, name: str, value: float = 1.0) -> None:
        """Increment a named counter."""
        self.counters[name] += value

    def observe(self, name: str, value: float) -> None:
        """Record a numeric observation."""
        self.observations[name].append(value)


class Timer:
    """Context manager that records elapsed milliseconds into a registry."""

    def __init__(self, registry: MetricsRegistry, metric: str):
        """Bind *registry* and *metric* name for elapsed-time recording."""
        self.registry = registry
        self.metric = metric
        self.started = 0.0

    def __enter__(self) -> "Timer":
        """Start the timer and return self for use in a with-statement."""
        self.started = perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Record elapsed milliseconds into the bound registry."""
        self.registry.observe(self.metric, (perf_counter() - self.started) * 1000)


@dataclass(frozen=True)
class RepairRunObservation:
    """Provider-neutral evidence emitted for one bounded repair attempt."""

    repository: str
    failure_class: str
    action: str
    attempts: int
    success: bool
    latency_seconds: float
    evaluation_score: float | None = None
    human_escalated: bool = False
    regression_detected: bool = False
    estimated_cost_usd: float | None = None
    attributes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProductionGateTarget:
    """Quality and safety thresholds required before autonomous rollout."""

    minimum_success_rate: float = 0.85
    maximum_false_repair_rate: float = 0.02
    maximum_regression_rate: float = 0.01
    maximum_p95_latency_seconds: float = 300.0
    maximum_human_escalation_rate: float = 0.40


@dataclass(frozen=True)
class ProductionGateReport:
    """Aggregated production-readiness result for a benchmark/replay window."""

    passed: bool
    observations: int
    success_rate: float
    false_repair_rate: float
    regression_rate: float
    p95_latency_seconds: float
    human_escalation_rate: float
    violations: tuple[str, ...]


def _rate(count: int, total: int) -> float:
    """Return count/total, or 0.0 when total is zero."""
    return count / total if total else 0.0


def _p95(values: list[float]) -> float:
    """Return the 95th percentile of *values*, or 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, int(round(0.95 * (len(ordered) - 1))))
    return ordered[index]


def evaluate_production_gate(
    observations: list[RepairRunObservation],
    *,
    target: ProductionGateTarget | None = None,
) -> ProductionGateReport:
    """Evaluate observed repair behavior against explicit rollout thresholds."""

    target = target or ProductionGateTarget()
    total = len(observations)
    success_rate = _rate(sum(item.success for item in observations), total)
    false_repairs = sum(
        item.action == "READY_FOR_POLICY_GATE" and not item.success for item in observations
    )
    false_repair_rate = _rate(false_repairs, total)
    regression_rate = _rate(sum(item.regression_detected for item in observations), total)
    escalation_rate = _rate(sum(item.human_escalated for item in observations), total)
    p95_latency = _p95([item.latency_seconds for item in observations])

    violations: list[str] = []
    if total == 0:
        violations.append("no observations available")
    if success_rate < target.minimum_success_rate:
        violations.append("success rate below target")
    if false_repair_rate > target.maximum_false_repair_rate:
        violations.append("false repair rate above target")
    if regression_rate > target.maximum_regression_rate:
        violations.append("regression rate above target")
    if p95_latency > target.maximum_p95_latency_seconds:
        violations.append("p95 latency above target")
    if escalation_rate > target.maximum_human_escalation_rate:
        violations.append("human escalation rate above target")

    return ProductionGateReport(
        passed=not violations,
        observations=total,
        success_rate=success_rate,
        false_repair_rate=false_repair_rate,
        regression_rate=regression_rate,
        p95_latency_seconds=p95_latency,
        human_escalation_rate=escalation_rate,
        violations=tuple(violations),
    )


class OpenTelemetryRecorder:
    """Emit repair traces and metrics when the observability extra is installed."""

    def __init__(self, service_name: str = "ci-failure-orchestrator") -> None:
        """Initialise the OpenTelemetry providers, tracer, and metric instruments.

        Raises RuntimeError when the optional ``observability`` dependencies are
        not installed.
        """
        try:
            from opentelemetry import metrics, trace
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
        except ImportError as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError(
                "OpenTelemetry support requires the 'observability' optional dependency"
            ) from exc

        resource = Resource.create({"service.name": service_name})
        tracer_provider = TracerProvider(resource=resource)
        meter_provider = MeterProvider(resource=resource)
        trace.set_tracer_provider(tracer_provider)
        metrics.set_meter_provider(meter_provider)

        self._tracer = trace.get_tracer(__name__)
        meter = metrics.get_meter(__name__)
        self._runs = meter.create_counter("ci_repair_runs")
        self._latency = meter.create_histogram("ci_repair_latency_seconds")
        self._escalations = meter.create_counter("ci_repair_human_escalations")
        self._regressions = meter.create_counter("ci_repair_regressions")

    def record(self, observation: RepairRunObservation) -> None:
        """Emit metrics for one completed repair observation."""

        attrs = {
            "repository": observation.repository,
            "failure_class": observation.failure_class,
            "action": observation.action,
            "success": str(observation.success).lower(),
            **dict(observation.attributes),
        }
        self._runs.add(1, attrs)
        self._latency.record(observation.latency_seconds, attrs)
        if observation.human_escalated:
            self._escalations.add(1, attrs)
        if observation.regression_detected:
            self._regressions.add(1, attrs)

    @contextmanager
    def repair_span(self, repository: str, failure_class: str) -> Iterator[None]:
        """Trace a repair attempt without coupling the core to an exporter."""

        started = perf_counter()
        with self._tracer.start_as_current_span("ci.repair") as span:
            span.set_attribute("ci.repository", repository)
            span.set_attribute("ci.failure_class", failure_class)
            try:
                yield
            finally:
                span.set_attribute("ci.duration_seconds", perf_counter() - started)

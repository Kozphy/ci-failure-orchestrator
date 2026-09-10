"""Dependency-free telemetry hooks for CI repair operations.

This module provides lightweight telemetry hooks for metrics collection that can
be bridged to OpenTelemetry or other observability platforms later. The current
implementation is dependency-free and uses in-memory storage for counters and
observations, suitable for development and testing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from time import perf_counter
from typing import Callable


@dataclass
class MetricsRegistry:
    """In-memory metrics registry for counters and observations.

    This registry provides a simple, dependency-free way to collect metrics
    during CI repair operations. It can be bridged to OpenTelemetry or other
    observability platforms for production deployments.

    Attributes:
        counters: Dictionary mapping counter names to cumulative values.
        observations: Dictionary mapping observation names to lists of observed values.

    Engineering Notes:
        - Trade-off: In-memory storage is simple but not persistent across restarts.
        - Design: Simple counter and observation primitives for easy bridging to OpenTelemetry.
        - Performance: Minimal overhead for in-memory operations.
    """

    counters: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    observations: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def inc(self, name: str, value: float = 1.0) -> None:
        """Increment a counter metric by a specified value.

        Args:
            name: Counter metric name (e.g., "repairs_attempted").
            value: Value to increment by (default: 1.0).

        Side Effects:
            - Updates the counter in the in-memory registry.
        """
        self.counters[name] += value

    def observe(self, name: str, value: float) -> None:
        """Record an observation value for a metric.

        Args:
            name: Observation metric name (e.g., "repair_latency_ms").
            value: Observed value to record.

        Side Effects:
            - Appends the value to the observation list in the in-memory registry.
        """
        self.observations[name].append(value)


class Timer:
    """Context manager for timing operations and recording metrics.

    This timer measures execution time in milliseconds and records it as an
    observation in the provided metrics registry. It is designed for use with
    the `with` statement for automatic timing and metric recording.

    Attributes:
        registry: MetricsRegistry to record the timing metric.
        metric: Name of the metric to record the timing under.
        started: Timestamp when the timer was started (seconds since epoch).

    Example:
        ```python
        registry = MetricsRegistry()
        with Timer(registry, "repair_duration_ms"):
            # Perform repair operation
            pass
        # Timing automatically recorded to registry.observations["repair_duration_ms"]
        ```
    """

    def __init__(self, registry: MetricsRegistry, metric: str):
        """Initialize the timer with a metrics registry and metric name.

        Args:
            registry: MetricsRegistry to record the timing metric.
            metric: Name of the metric to record the timing under.
        """
        self.registry = registry
        self.metric = metric
        self.started = 0.0

    def __enter__(self) -> "Timer":
        """Enter the context manager and start the timer.

        Returns:
            The timer instance for chaining or reference.
        """
        self.started = perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Exit the context manager, stop the timer, and record the metric.

        Args:
            exc_type: Exception type if an exception occurred (unused).
            exc: Exception instance if an exception occurred (unused).
            tb: Traceback if an exception occurred (unused).

        Side Effects:
            - Records the elapsed time in milliseconds to the metrics registry.
        """
        self.registry.observe(self.metric, (perf_counter() - self.started) * 1000)

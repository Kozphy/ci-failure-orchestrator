"""Dependency-free telemetry hooks that can be bridged to OpenTelemetry later."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from time import perf_counter
from typing import Callable


@dataclass
class MetricsRegistry:
    counters: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    observations: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def inc(self, name: str, value: float = 1.0) -> None:
        self.counters[name] += value

    def observe(self, name: str, value: float) -> None:
        self.observations[name].append(value)


class Timer:
    def __init__(self, registry: MetricsRegistry, metric: str):
        self.registry = registry
        self.metric = metric
        self.started = 0.0

    def __enter__(self) -> "Timer":
        self.started = perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.registry.observe(self.metric, (perf_counter() - self.started) * 1000)

"""Vendor-neutral continuous-integration contracts for the software factory.

This module isolates CI-provider concerns from orchestration logic. GitHub
Actions, CircleCI, or future CI systems can implement :class:`CIAdapter`
without changing the factory control plane. Unknown providers and malformed
registry keys fail closed instead of silently selecting a default backend.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class CIState(str, Enum):
    """Normalized lifecycle states shared by all CI providers."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CIRun:
    """Normalized identity and status for one CI execution."""

    provider: str
    run_id: str
    state: CIState
    url: str = ""


@dataclass(frozen=True)
class CILog:
    """Text log payload associated with a normalized CI run."""

    run_id: str
    text: str


class CIAdapter(Protocol):
    """Vendor-neutral CI contract for triggering and inspecting pipelines.

    Implementations must expose stable run identifiers and normalized states.
    Retry behavior is intentionally explicit so an agent cannot hide a failed
    run by creating an unrelated replacement pipeline.
    """

    def trigger(self, ref: str) -> CIRun:
        """Start CI for ``ref`` and return the normalized run."""
        ...

    def status(self, run_id: str) -> CIRun:
        """Return the latest normalized state for ``run_id``."""
        ...

    def logs(self, run_id: str) -> CILog:
        """Return diagnostic logs used by evaluators or repair agents."""
        ...

    def retry_failed(self, run_id: str) -> CIRun:
        """Retry failed work for ``run_id`` and return the resulting run."""
        ...


class CIRegistry:
    """Register and resolve CI adapters by stable, case-insensitive name."""

    def __init__(self) -> None:
        """Create an empty provider registry."""
        self._providers: dict[str, CIAdapter] = {}

    def register(self, name: str, adapter: CIAdapter) -> None:
        """Register ``adapter`` under ``name``.

        Raises:
            ValueError: If the normalized provider name is empty.
        """
        key = name.strip().lower()
        if not key:
            raise ValueError("CI provider name must not be empty")
        self._providers[key] = adapter

    def get(self, name: str) -> CIAdapter:
        """Resolve a provider by name, failing closed if it is unknown."""
        key = name.strip().lower()
        try:
            return self._providers[key]
        except KeyError as exc:
            raise KeyError(f"unknown CI provider: {name}") from exc

    def providers(self) -> tuple[str, ...]:
        """Return registered provider names in deterministic order."""
        return tuple(sorted(self._providers))

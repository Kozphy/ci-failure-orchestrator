from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class CIState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CIRun:
    provider: str
    run_id: str
    state: CIState
    url: str = ""


@dataclass(frozen=True)
class CILog:
    run_id: str
    text: str


class CIAdapter(Protocol):
    """Vendor-neutral CI contract for GitHub Actions, CircleCI, etc."""

    def trigger(self, ref: str) -> CIRun: ...

    def status(self, run_id: str) -> CIRun: ...

    def logs(self, run_id: str) -> CILog: ...

    def retry_failed(self, run_id: str) -> CIRun: ...


class CIRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, CIAdapter] = {}

    def register(self, name: str, adapter: CIAdapter) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("CI provider name must not be empty")
        self._providers[key] = adapter

    def get(self, name: str) -> CIAdapter:
        key = name.strip().lower()
        try:
            return self._providers[key]
        except KeyError as exc:
            raise KeyError(f"unknown CI provider: {name}") from exc

    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

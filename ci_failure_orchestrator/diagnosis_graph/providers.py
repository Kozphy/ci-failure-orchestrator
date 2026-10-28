"""Hypothesis providers for the diagnosis graph.

Model output is a category hypothesis only. It never becomes the final decision;
``FailureClassifier`` and the verify node own that.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


class ProviderTransientError(RuntimeError):
    """Retryable provider failure (network blip, 5xx). Not a timeout."""


class ProviderHardError(RuntimeError):
    """Non-retryable provider failure."""


class HypothesisProvider(Protocol):
    """Produces a category hypothesis for a CI failure."""

    name: str

    def hypothesize(
        self,
        *,
        message: str,
        log_excerpt: str,
        workflow: str,
        job: str,
        failed_step: str,
    ) -> tuple[str, str]:
        """Return ``(category, rationale)``."""


@dataclass
class MockHypothesisProvider:
    """Deterministic offline provider. No credentials and no network."""

    name: str = "mock"
    category: str = "test_failure"
    rationale: str = "mock hypothesis: assertion wording in the log"
    delay_seconds: float = 0.0
    failures_before_success: int = 0
    hard_fail: bool = False

    def __post_init__(self) -> None:
        self._calls = 0

    @property
    def calls(self) -> int:
        """How many times ``hypothesize`` was entered."""
        return self._calls

    def hypothesize(
        self,
        *,
        message: str,
        log_excerpt: str,
        workflow: str,
        job: str,
        failed_step: str,
    ) -> tuple[str, str]:
        self._calls += 1
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        if self.hard_fail:
            raise ProviderHardError("mock provider hard failure")
        if self._calls <= self.failures_before_success:
            raise ProviderTransientError(f"mock provider transient failure #{self._calls}")
        _ = (message, log_excerpt, workflow, job, failed_step)
        return self.category, self.rationale

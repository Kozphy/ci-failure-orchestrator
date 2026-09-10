"""Provider-neutral routing and tournament selection for CI repair workers.

The router chooses eligible workers from declared capabilities and budget constraints.
Workers still cannot approve, merge, or release their own changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .github_repair_adapter import AgentTask
from .supervisor import RepairAuthority


@dataclass(frozen=True)
class WorkerProfile:
    """Declared worker capabilities used by routing policy."""

    name: str
    provider: str
    authorities: tuple[RepairAuthority, ...]
    supported_failure_classes: tuple[str, ...] = ()
    max_cost_usd: float = 1.0
    max_latency_ms: int = 120_000

    def supports(self, task: AgentTask) -> bool:
        """Return whether the worker is eligible for the task contract."""

        if task.authority not in self.authorities:
            return False
        return not self.supported_failure_classes or task.failure_class in self.supported_failure_classes


@dataclass(frozen=True)
class CandidateResult:
    """One independently measurable worker candidate."""

    worker: str
    provider: str
    patch_id: str
    tests_passed: bool
    regression_free: bool
    policy_passed: bool
    security_passed: bool
    cost_usd: float
    latency_ms: int
    changed_lines: int
    confidence: float = 0.0

    @property
    def safe(self) -> bool:
        """Return whether the candidate cleared all hard safety gates."""

        return (
            self.tests_passed
            and self.regression_free
            and self.policy_passed
            and self.security_passed
        )


@dataclass(frozen=True)
class TournamentDecision:
    """Selected candidate plus evidence for why it won."""

    winner: CandidateResult | None
    rejected: tuple[CandidateResult, ...]
    reason: str


def route_workers(
    task: AgentTask,
    workers: Iterable[WorkerProfile],
    *,
    remaining_cost_usd: float,
) -> tuple[WorkerProfile, ...]:
    """Return eligible workers without exceeding the remaining incident budget."""

    eligible = [
        worker
        for worker in workers
        if worker.supports(task) and worker.max_cost_usd <= remaining_cost_usd
    ]
    return tuple(sorted(eligible, key=lambda w: (w.max_cost_usd, w.max_latency_ms, w.name)))


def select_candidate(candidates: Iterable[CandidateResult]) -> TournamentDecision:
    """Choose the safest candidate, then minimize cost, latency, and patch size.

    Unsafe candidates never win regardless of confidence or cost.
    """

    all_candidates = tuple(candidates)
    safe = tuple(candidate for candidate in all_candidates if candidate.safe)
    rejected = tuple(candidate for candidate in all_candidates if not candidate.safe)
    if not safe:
        return TournamentDecision(None, rejected, "no_safe_candidate")

    winner = min(
        safe,
        key=lambda c: (
            c.cost_usd,
            c.latency_ms,
            c.changed_lines,
            -c.confidence,
            c.worker,
        ),
    )
    return TournamentDecision(winner, rejected, "lowest_cost_safe_candidate")

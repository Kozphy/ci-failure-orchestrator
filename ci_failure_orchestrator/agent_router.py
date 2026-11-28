"""Provider-neutral routing for untrusted external coding agents.

The router chooses eligible workers from declared capabilities and budget
constraints. Workers propose diffs only; they cannot approve, merge, or release.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class WorkerAuthority(str, Enum):
    """Host-issued authority for what an external agent may attempt."""

    PROPOSE_ONLY = "propose_only"
    AUTONOMOUS_PATCH = "autonomous_patch"
    HUMAN_GATED = "human_gated"


@dataclass(frozen=True)
class AgentTask:
    """Bounded task contract passed to an external coding agent."""

    objective: str
    failure_class: str
    authority: WorkerAuthority
    allowed_paths: tuple[str, ...]
    required_gates: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    evidence: tuple[str, ...]
    idempotency_key: str


@dataclass(frozen=True)
class WorkerProfile:
    """Declared worker capabilities used by routing policy."""

    name: str
    provider: str
    authorities: tuple[WorkerAuthority, ...]
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
    """One independently measurable worker candidate after verification."""

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

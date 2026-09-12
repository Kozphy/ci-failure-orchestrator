from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from .event_bus import ControlPlaneEvent


class AgentName(StrEnum):
    OPENCLAW = "openclaw"
    CODEX = "codex"
    AIDER = "aider"


@dataclass(slots=True)
class RepairCandidate:
    agent: AgentName
    summary: str
    patch_ref: str
    test_score: float = 0.0
    security_score: float = 0.0
    regression_score: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


class RepairWorker(Protocol):
    name: AgentName

    def propose(self, event: ControlPlaneEvent) -> RepairCandidate | None: ...


class CandidateStore:
    """Durable-store boundary; in-memory implementation keeps the core deterministic."""

    def __init__(self) -> None:
        self._items: dict[str, list[RepairCandidate]] = {}

    def put(self, event_id: str, candidate: RepairCandidate) -> None:
        self._items.setdefault(event_id, []).append(candidate)

    def list(self, event_id: str) -> list[RepairCandidate]:
        return list(self._items.get(event_id, []))


@dataclass(frozen=True, slots=True)
class VerificationResult:
    passed: bool
    test_score: float
    security_score: float
    regression_score: float
    reasons: tuple[str, ...] = ()


class Verifier(Protocol):
    def verify(self, candidate: RepairCandidate) -> VerificationResult: ...


@dataclass(frozen=True, slots=True)
class RiskDecision:
    score: float
    requires_human_approval: bool
    blocked: bool
    reasons: tuple[str, ...] = ()


class RiskEngine:
    """Turn independent evidence into a bounded 0..1 risk score."""

    def evaluate(self, verification: VerificationResult) -> RiskDecision:
        risk = 1.0 - (
            0.50 * verification.test_score
            + 0.30 * verification.security_score
            + 0.20 * verification.regression_score
        )
        risk = min(1.0, max(0.0, risk))
        return RiskDecision(
            score=risk,
            requires_human_approval=risk >= 0.25,
            blocked=(not verification.passed or risk >= 0.70),
            reasons=verification.reasons,
        )


class IntakePolicy(Protocol):
    def allow(self, event: ControlPlaneEvent) -> tuple[bool, tuple[str, ...]]: ...


class DraftPRPublisher(Protocol):
    def create_draft_pr(
        self,
        event: ControlPlaneEvent,
        candidate: RepairCandidate,
        risk: RiskDecision,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    event_id: str
    policy_allowed: bool
    candidates_seen: int
    selected_agent: AgentName | None = None
    risk_score: float | None = None
    draft_pr_ref: str | None = None
    status: str = "blocked"
    reasons: tuple[str, ...] = ()


class EventDrivenControlPlane:
    """GitHub/CI/endpoint event -> policy -> agents -> verify -> risk -> Draft PR.

    Agents are proposal workers only. They cannot approve, merge, bypass policy,
    or decide that their own patch is safe enough to ship.
    """

    def __init__(
        self,
        *,
        policy: IntakePolicy,
        workers: list[RepairWorker],
        verifier: Verifier,
        candidate_store: CandidateStore,
        risk_engine: RiskEngine,
        publisher: DraftPRPublisher,
    ) -> None:
        self.policy = policy
        self.workers = workers
        self.verifier = verifier
        self.candidate_store = candidate_store
        self.risk_engine = risk_engine
        self.publisher = publisher

    def handle(self, event: ControlPlaneEvent) -> OrchestrationResult:
        allowed, policy_reasons = self.policy.allow(event)
        if not allowed:
            return OrchestrationResult(
                event_id=event.id,
                policy_allowed=False,
                candidates_seen=0,
                reasons=policy_reasons,
            )

        for worker in self.workers:
            candidate = worker.propose(event)
            if candidate is not None:
                self.candidate_store.put(event.id, candidate)

        candidates = self.candidate_store.list(event.id)
        if not candidates:
            return OrchestrationResult(
                event_id=event.id,
                policy_allowed=True,
                candidates_seen=0,
                status="no_candidate",
            )

        evaluated: list[tuple[RepairCandidate, VerificationResult, RiskDecision]] = []
        for candidate in candidates:
            verification = self.verifier.verify(candidate)
            risk = self.risk_engine.evaluate(verification)
            evaluated.append((candidate, verification, risk))

        viable = [item for item in evaluated if not item[2].blocked]
        if not viable:
            reasons = tuple(
                reason
                for _, verification, risk in evaluated
                for reason in (*verification.reasons, *risk.reasons)
            )
            return OrchestrationResult(
                event_id=event.id,
                policy_allowed=True,
                candidates_seen=len(candidates),
                status="verification_blocked",
                reasons=reasons,
            )

        selected, _, risk = min(viable, key=lambda item: item[2].score)
        pr_ref = self.publisher.create_draft_pr(event, selected, risk)
        status = "awaiting_human_review" if risk.requires_human_approval else "draft_pr_created"
        return OrchestrationResult(
            event_id=event.id,
            policy_allowed=True,
            candidates_seen=len(candidates),
            selected_agent=selected.agent,
            risk_score=risk.score,
            draft_pr_ref=pr_ref,
            status=status,
        )

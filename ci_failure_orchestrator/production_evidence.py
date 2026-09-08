from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

from .policy import PolicyDecision
from .tournament import TournamentResult


@dataclass(frozen=True)
class ProductionEvidence:
    root_stage: str
    selected_agent: str | None
    action: str
    reason: str
    evaluation_score: float | None
    risk_score: float | None
    cost_usd: float | None
    latency_ms: int | None
    candidate_count: int
    evidence_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_production_evidence(
    *,
    root_stage: str,
    tournament: TournamentResult,
    policy: PolicyDecision,
) -> ProductionEvidence:
    winner = tournament.winner
    payload = {
        "root_stage": root_stage,
        "selected_agent": winner.agent_name if winner else None,
        "action": policy.action,
        "reason": policy.reason,
        "evaluation_score": winner.evaluation.score if winner and winner.evaluation else None,
        "risk_score": winner.risk_score if winner else None,
        "cost_usd": winner.cost_usd if winner else None,
        "latency_ms": winner.latency_ms if winner else None,
        "candidate_count": len(tournament.candidates),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return ProductionEvidence(
        **payload,
        evidence_hash=sha256(encoded).hexdigest(),
    )

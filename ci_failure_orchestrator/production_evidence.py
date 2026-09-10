from __future__ import annotations

"""Production evidence generation for CI repair platform.

This module builds machine-readable evidence artifacts that capture
the complete decision trail for a repair: root cause, tournament result,
policy decision, and all associated metadata. Evidence is hash-signed
for tamper detection.

Module responsibility:
    - Aggregate tournament and policy results into production evidence
    - Compute SHA-256 evidence hash for integrity verification
    - Provide JSON-serializable evidence for audit trails

Key invariants:
    - ProductionEvidence is immutable (frozen dataclass)
    - Evidence hash is computed from canonical JSON representation
    - All metadata is extracted from tournament winner and policy decision

Safety boundaries:
    - Evidence generation is pure computation from inputs
    - No external system calls or mutations
    - Null/None values are preserved as None (not substituted)

Audit Notes:
    - evidence_hash provides tamper-evidence for the evidence payload
    - All values are extracted from tournament and policy inputs
    - Winner information is captured including agent name, scores, costs, latency
"""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

from .policy import PolicyDecision
from .tournament import TournamentResult


@dataclass(frozen=True)
class ProductionEvidence:
    """Machine-readable evidence of a production repair decision.

    Captures all material facts about a repair: the root cause stage,
    the selected agent (if any), the action taken, the reasoning, and
    all associated quality metrics. The evidence is tamper-evident via
    a SHA-256 hash computed from the canonical payload.

    Attributes:
        root_stage: Identified root cause stage
        selected_agent: Name of the agent that produced the accepted repair, or None
        action: Policy action taken (e.g., "READY_FOR_CANARY", "ESCALATE_HUMAN")
        reason: Human-readable explanation for the policy decision
        evaluation_score: Independent evaluation score for the repair (0.0-1.0)
        risk_score: Risk score assigned to the repair (0.0-1.0)
        cost_usd: Cost of the repair in USD
        latency_ms: Repair execution latency in milliseconds
        candidate_count: Total number of candidates considered in tournament
        evidence_hash: SHA-256 hash of the canonical evidence payload
    """

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
        """Return JSON-serializable dictionary representation.

        Returns:
            Dictionary with all evidence fields
        """
        return asdict(self)


def build_production_evidence(
    *,
    root_stage: str,
    tournament: TournamentResult,
    policy: PolicyDecision,
) -> ProductionEvidence:
    """Build production evidence from tournament and policy results.

    Extracts all relevant data from the tournament winner and policy
    decision, constructs a canonical JSON payload, and computes a
    SHA-256 hash for tamper-evidence.

    Args:
        root_stage: The identified root cause stage
        tournament: TournamentResult containing all candidates and the winner
        policy: PolicyDecision containing the action and reason

    Returns:
        ProductionEvidence with all extracted data and computed evidence_hash

    Side effects:
        None. Pure computation from inputs.

    Audit Notes:
        - If tournament has no winner, all winner-derived fields are None
        - evidence_hash is computed from sorted, compact JSON
        - All inputs are preserved exactly in the output evidence
    """

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

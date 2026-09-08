from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Iterable, Mapping


@dataclass(frozen=True)
class ProductionMetrics:
    repair_success_rate: float
    regression_rate: float
    p95_latency_seconds: float
    cost_per_success_usd: float
    critical_security_findings: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProductionPolicy:
    min_repair_success_rate: float = 0.90
    max_regression_rate: float = 0.02
    max_p95_latency_seconds: float = 30.0
    max_cost_per_success_usd: float = 0.20
    max_critical_security_findings: int = 0


@dataclass(frozen=True)
class GateResult:
    passed: bool
    checks: dict[str, bool]

    @property
    def decision(self) -> str:
        return "PASS" if self.passed else "BLOCK"

    def to_dict(self) -> dict:
        return {"passed": self.passed, "decision": self.decision, "checks": self.checks}


def evaluate_production_gate(
    metrics: ProductionMetrics,
    policy: ProductionPolicy | None = None,
) -> GateResult:
    policy = policy or ProductionPolicy()
    checks = {
        "repair_success_rate": metrics.repair_success_rate >= policy.min_repair_success_rate,
        "regression_rate": metrics.regression_rate <= policy.max_regression_rate,
        "p95_latency_seconds": metrics.p95_latency_seconds <= policy.max_p95_latency_seconds,
        "cost_per_success_usd": metrics.cost_per_success_usd <= policy.max_cost_per_success_usd,
        "critical_security_findings": metrics.critical_security_findings <= policy.max_critical_security_findings,
    }
    return GateResult(passed=all(checks.values()), checks=checks)


def metrics_from_mapping(data: Mapping[str, object]) -> ProductionMetrics:
    return ProductionMetrics(
        repair_success_rate=float(data["repair_success_rate"]),
        regression_rate=float(data["regression_rate"]),
        p95_latency_seconds=float(data["p95_latency_seconds"]),
        cost_per_success_usd=float(data["cost_per_success_usd"]),
        critical_security_findings=int(data.get("critical_security_findings", 0)),
    )


@dataclass(frozen=True)
class ProofArtifact:
    kind: str
    uri: str
    digest: str | None = None


@dataclass(frozen=True)
class ProductionProofBundle:
    repository: str
    run_id: str
    commit_sha: str
    gate_decision: str
    evaluator_score: float
    regression_free: bool
    canary_decision: str
    slo_met: bool
    artifacts: tuple[ProofArtifact, ...]
    created_at: str
    proof_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_production_proof(
    *,
    repository: str,
    run_id: str,
    commit_sha: str,
    gate_decision: str,
    evaluator_score: float,
    regression_free: bool,
    canary_decision: str,
    slo_met: bool,
    artifacts: Iterable[ProofArtifact] = (),
) -> ProductionProofBundle:
    artifact_tuple = tuple(artifacts)
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "repository": repository,
        "run_id": run_id,
        "commit_sha": commit_sha,
        "gate_decision": gate_decision,
        "evaluator_score": evaluator_score,
        "regression_free": regression_free,
        "canary_decision": canary_decision,
        "slo_met": slo_met,
        "artifacts": [asdict(a) for a in artifact_tuple],
        "created_at": created_at,
    }
    proof_hash = sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return ProductionProofBundle(
        repository=repository,
        run_id=run_id,
        commit_sha=commit_sha,
        gate_decision=gate_decision,
        evaluator_score=evaluator_score,
        regression_free=regression_free,
        canary_decision=canary_decision,
        slo_met=slo_met,
        artifacts=artifact_tuple,
        created_at=created_at,
        proof_hash=proof_hash,
    )

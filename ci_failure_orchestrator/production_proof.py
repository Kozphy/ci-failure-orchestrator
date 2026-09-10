from __future__ import annotations

"""Production proof bundle generation for CI repair platform.

This module provides tamper-evident release-level summary artifacts that
bind together all production readiness evidence into a single verifiable
bundle. The production proof represents release authority evidence rather
than an agent's claim.

Module responsibility:
    - Define production metrics and policy thresholds
    - Evaluate production gate compliance
    - Build tamper-evident proof bundles
    - Compute SHA-256 proof hashes for bundle integrity

Key invariants:
    - ProductionProofBundle is immutable (frozen dataclass)
    - Proof hash is computed from canonical JSON representation
    - All timestamps are UTC
    - Artifact URIs and digests are preserved as provided

Safety boundaries:
    - evaluate_production_gate() uses fail-closed semantics
    - Proof hash computation uses deterministic JSON serialization
    - Empty artifacts list is valid (default empty tuple)

Audit Notes:
    - Production proof bundles are release-level artifacts
    - Proof hash provides tamper-evidence for the entire bundle
    - All inputs are preserved in the bundle for auditability
    - created_at timestamp is UTC and machine-generated
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Iterable, Mapping


@dataclass(frozen=True)
class ProductionMetrics:
    """Observed production metrics for gate evaluation.

    Captures the key reliability and cost metrics used to determine
    whether a release should proceed to production.

    Attributes:
        repair_success_rate: Fraction of successful repairs (0.0-1.0)
        regression_rate: Fraction of repairs introducing regressions (0.0-1.0)
        p95_latency_seconds: 95th percentile repair latency in seconds
        cost_per_success_usd: Average cost per successful repair in USD
        critical_security_findings: Count of critical security issues found
    """

    repair_success_rate: float
    regression_rate: float
    p95_latency_seconds: float
    cost_per_success_usd: float
    critical_security_findings: int = 0

    def to_dict(self) -> dict:
        """Return JSON-serializable dictionary.

        Returns:
            Dictionary with all metric values
        """
        return asdict(self)


@dataclass(frozen=True)
class ProductionPolicy:
    """Threshold policy for production gate decisions.

    Defines the acceptable boundaries for production readiness.
    All checks must pass for the gate to be satisfied.

    Attributes:
        min_repair_success_rate: Minimum acceptable repair success rate
        max_regression_rate: Maximum acceptable regression rate
        max_p95_latency_seconds: Maximum acceptable 95th percentile latency
        max_cost_per_success_usd: Maximum acceptable cost per success
        max_critical_security_findings: Maximum acceptable critical security findings
    """

    min_repair_success_rate: float = 0.90
    max_regression_rate: float = 0.02
    max_p95_latency_seconds: float = 30.0
    max_cost_per_success_usd: float = 0.20
    max_critical_security_findings: int = 0


@dataclass(frozen=True)
class GateResult:
    """Result of production gate evaluation.

    Captures the pass/fail status and individual check results.

    Attributes:
        passed: True if all checks passed, False otherwise
        checks: Dictionary mapping check names to boolean results
    """

    passed: bool
    checks: dict[str, bool]

    @property
    def decision(self) -> str:
        """Return the gate decision string.

        Returns:
            "PASS" if all checks passed, "BLOCK" otherwise
        """
        return "PASS" if self.passed else "BLOCK"

    def to_dict(self) -> dict:
        """Return JSON-serializable dictionary.

        Returns:
            Dictionary with passed, decision, and checks
        """
        return {"passed": self.passed, "decision": self.decision, "checks": self.checks}


def evaluate_production_gate(
    metrics: ProductionMetrics,
    policy: ProductionPolicy | None = None,
) -> GateResult:
    """Evaluate production readiness against policy thresholds.

    Performs fail-closed evaluation: all checks must pass for the gate
    to be satisfied. Returns a GateResult with the outcome and individual
    check results.

    Args:
        metrics: ProductionMetrics containing observed values
        policy: ProductionPolicy defining thresholds; defaults to standard policy

    Returns:
        GateResult with overall pass/fail and individual check results

    Side effects:
        None. Pure computation from inputs.

    Audit Notes:
        - All checks are evaluated independently
        - GateResult.passed is True only if all checks pass
        - Individual check failures are recorded in GateResult.checks
    """

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
    """Reference to an external artifact included in the proof bundle.

    Attributes:
        kind: Type of artifact (e.g., "benchmark-result", "slo-report", "audit-log")
        uri: Location of the artifact (file path, URL, or other identifier)
        digest: Optional cryptographic digest of the artifact content
    """

    kind: str
    uri: str
    digest: str | None = None


@dataclass(frozen=True)
class ProductionProofBundle:
    """Tamper-evident production proof bundle.

    Binds together all production readiness evidence into a single
    release-level artifact with a cryptographic proof hash.

    Attributes:
        repository: Repository identifier for this proof
        run_id: Unique identifier for this run/proof
        commit_sha: Git commit SHA this proof applies to
        gate_decision: Production gate decision ("PASS" or "BLOCK")
        evaluator_score: Independent evaluator score (0.0-1.0)
        regression_free: Whether regression checks passed
        canary_decision: Canary deployment decision
        slo_met: Whether SLO targets are satisfied
        artifacts: Tuple of ProofArtifact references
        created_at: UTC timestamp of bundle creation (ISO 8601 format)
        proof_hash: SHA-256 hash of the canonical bundle payload
    """

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
        """Return JSON-serializable dictionary representation.

        Returns:
            Dictionary with all bundle fields
        """
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
    """Build a tamper-evident production proof bundle.

    Creates a ProductionProofBundle with all provided evidence and
    computes a SHA-256 proof hash from the canonical JSON representation
    of the payload (excluding the hash itself).

    The hash is computed from a sorted, deterministic JSON serialization
    to ensure reproducibility and tamper-detection.

    Args:
        repository: Repository identifier
        run_id: Unique run identifier
        commit_sha: Git commit SHA
        gate_decision: Production gate decision string
        evaluator_score: Independent evaluator score
        regression_free: Regression check result
        canary_decision: Canary decision string
        slo_met: SLO compliance boolean
        artifacts: Iterable of ProofArtifact to include in bundle

    Returns:
        ProductionProofBundle with computed proof_hash

    Side effects:
        None. Pure computation from inputs.

    Audit Notes:
        - proof_hash is computed from canonical JSON with sorted keys
        - created_at is set to current UTC time at call time
        - All inputs are preserved exactly in the bundle
        - Changing any input will result in a different proof_hash
    """

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

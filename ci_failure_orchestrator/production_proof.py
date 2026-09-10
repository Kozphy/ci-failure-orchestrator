"""Production proof generation for tamper-evident release evidence.

This module provides production gate evaluation, metrics validation, and
tamper-evident proof bundle generation for CI repair releases, including
SHA-256 hashing for cryptographic integrity verification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Iterable, Mapping


@dataclass(frozen=True)
class ProductionMetrics:
    """Production metrics for CI repair operations.

    Attributes:
        repair_success_rate: Proportion of successful repairs in production.
        regression_rate: Proportion of repairs that introduced regressions.
        p95_latency_seconds: 95th percentile repair latency in seconds.
        cost_per_success_usd: Average cost per successful repair in USD.
        critical_security_findings: Number of critical security findings (default: 0).
    """

    repair_success_rate: float
    regression_rate: float
    p95_latency_seconds: float
    cost_per_success_usd: float
    critical_security_findings: int = 0

    def to_dict(self) -> dict:
        """Convert production metrics to a dictionary representation.

        Returns:
            Dictionary containing all metric fields.
        """
        return asdict(self)


@dataclass(frozen=True)
class ProductionPolicy:
    """Policy thresholds for production gate evaluation.

    Attributes:
        min_repair_success_rate: Minimum acceptable repair success rate (default: 0.90).
        max_regression_rate: Maximum acceptable regression rate (default: 0.02).
        max_p95_latency_seconds: Maximum acceptable 95th percentile latency (default: 30.0).
        max_cost_per_success_usd: Maximum acceptable cost per success (default: 0.20).
        max_critical_security_findings: Maximum acceptable critical findings (default: 0).
    """

    min_repair_success_rate: float = 0.90
    max_regression_rate: float = 0.02
    max_p95_latency_seconds: float = 30.0
    max_cost_per_success_usd: float = 0.20
    max_critical_security_findings: int = 0


@dataclass(frozen=True)
class GateResult:
    """Result from production gate evaluation.

    Attributes:
        passed: Whether all production gate checks passed.
        checks: Dictionary of individual check results by metric name.

    Computed Properties:
        decision: String decision ("PASS" or "BLOCK") based on passed status.
    """

    passed: bool
    checks: dict[str, bool]

    @property
    def decision(self) -> str:
        """Get the gate decision as a string.

        Returns:
            "PASS" if all checks passed, "BLOCK" otherwise.
        """
        return "PASS" if self.passed else "BLOCK"

    def to_dict(self) -> dict:
        """Convert the gate result to a dictionary representation.

        Returns:
            Dictionary containing passed status, decision, and individual check results.
        """
        return {"passed": self.passed, "decision": self.decision, "checks": self.checks}


def evaluate_production_gate(
    metrics: ProductionMetrics,
    policy: ProductionPolicy | None = None,
) -> GateResult:
    """Evaluate production metrics against policy thresholds.

    This function checks each production metric against its policy threshold
    and returns a comprehensive gate result with individual check results.

    Args:
        metrics: Observed production metrics to evaluate.
        policy: Production policy thresholds (defaults to conservative ProductionPolicy).

    Returns:
        GateResult with overall pass/fail status and individual check results.

    Checks Evaluated:
        - repair_success_rate: Must meet or exceed minimum threshold.
        - regression_rate: Must not exceed maximum threshold.
        - p95_latency_seconds: Must not exceed maximum threshold.
        - cost_per_success_usd: Must not exceed maximum threshold.
        - critical_security_findings: Must not exceed maximum threshold.

    Audit Notes:
        - Failed gate checks block production releases.
        - Security findings above threshold always fail the gate.
        - Recovery: Review failed metrics and adjust policy thresholds if needed.
        - Evidence: All gate evaluations include individual check results for audit.
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
    """Create ProductionMetrics from a mapping (e.g., dict or JSON object).

    Args:
        data: Mapping containing production metric fields.

    Returns:
        ProductionMetrics instance with values extracted from the mapping.

    Raises:
        KeyError: If required fields are missing from the mapping.
        ValueError: If field values cannot be converted to the expected types.
    """
    return ProductionMetrics(
        repair_success_rate=float(data["repair_success_rate"]),
        regression_rate=float(data["regression_rate"]),
        p95_latency_seconds=float(data["p95_latency_seconds"]),
        cost_per_success_usd=float(data["cost_per_success_usd"]),
        critical_security_findings=int(data.get("critical_security_findings", 0)),
    )


@dataclass(frozen=True)
class ProofArtifact:
    """Reference to an artifact included in the production proof bundle.

    Attributes:
        kind: Type of artifact (e.g., "log", "trace", "benchmark").
        uri: URI or path to the artifact.
        digest: Optional SHA-256 digest of the artifact content for integrity verification.
    """

    kind: str
    uri: str
    digest: str | None = None


@dataclass(frozen=True)
class ProductionProofBundle:
    """Tamper-evident proof bundle for production releases.

    This bundle binds together all evidence from a CI repair release into a
    single tamper-evident artifact with a SHA-256 proof hash for integrity
    verification.

    Attributes:
        repository: Repository identifier (e.g., "owner/repo").
        run_id: CI workflow run ID.
        commit_sha: Git commit SHA for the release.
        gate_decision: Production gate decision ("PASS" or "BLOCK").
        evaluator_score: Evaluator score for the repair proposal.
        regression_free: Whether the repair was regression-free.
        canary_decision: Canary promotion decision.
        slo_met: Whether SLO targets were met.
        artifacts: Tuple of proof artifacts supporting the release.
        created_at: UTC timestamp in ISO 8601 format.
        proof_hash: SHA-256 hash of the entire bundle for integrity verification.

    Audit Notes:
        - The proof hash provides tamper-evidence for the entire release bundle.
        - Any modification to the bundle invalidates the proof hash.
        - Recovery: Verify proof hash and review all artifacts before accepting release.
        - Evidence: The proof bundle includes all decision evidence for audit trails.
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
        """Convert the production proof bundle to a dictionary representation.

        Returns:
            Dictionary containing all bundle fields including nested artifacts.
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
    """Build a tamper-evident production proof bundle for a release.

    This function combines all release evidence into a single bundle with a
    SHA-256 proof hash for cryptographic integrity verification. The hash
    is computed over all bundle fields including artifacts and timestamp.

    Args:
        repository: Repository identifier (e.g., "owner/repo").
        run_id: CI workflow run ID.
        commit_sha: Git commit SHA for the release.
        gate_decision: Production gate decision ("PASS" or "BLOCK").
        evaluator_score: Evaluator score for the repair proposal.
        regression_free: Whether the repair was regression-free.
        canary_decision: Canary promotion decision.
        slo_met: Whether SLO targets were met.
        artifacts: Iterable of proof artifacts supporting the release.

    Returns:
        ProductionProofBundle with all evidence and SHA-256 proof hash.

    Hash Computation:
        The proof hash is computed as SHA-256(JSON.dumps(payload, sort_keys=True))
        where payload includes all bundle fields, artifacts, and UTC timestamp.
        Any modification to the bundle invalidates the proof hash.

    Audit Notes:
        - The proof hash provides tamper-evidence for the entire release bundle.
        - Timestamps are in UTC to ensure consistent hash computation across timezones.
        - Recovery: Verify proof hash matches recomputed hash from bundle data.
        - Evidence: The proof bundle serves as the release-level audit artifact.
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

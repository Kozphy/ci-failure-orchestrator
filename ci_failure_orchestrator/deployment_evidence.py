from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from .production_proof import ProductionMetrics, ProductionPolicy, evaluate_production_gate, metrics_from_mapping


class EvidenceValidationError(ValueError):
    """Raised when deployment evidence cannot support a production claim."""


@dataclass(frozen=True)
class DeploymentEvidence:
    deployment_id: str
    repository: str
    environment: str
    commit_sha: str
    artifact_sha256: str
    measured_at: str
    source: str
    metrics: ProductionMetrics
    canary_healthy: bool
    observability_healthy: bool
    rollback_ready: bool
    production_regression: bool

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["metrics"] = self.metrics.to_dict()
        return data


def _required_str(data: Mapping[str, object], key: str) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise EvidenceValidationError(f"missing required field: {key}")
    return value


def parse_deployment_evidence(data: Mapping[str, object]) -> DeploymentEvidence:
    source = _required_str(data, "source").lower()
    if source in {"example", "fixture", "synthetic", "simulated", "mock"}:
        raise EvidenceValidationError(
            f"source={source!r} cannot support a measured production claim"
        )

    environment = _required_str(data, "environment").lower()
    if environment != "production":
        raise EvidenceValidationError(
            f"environment must be 'production' for production evidence, got {environment!r}"
        )

    measured_at = _required_str(data, "measured_at")
    try:
        parsed_time = datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceValidationError("measured_at must be ISO-8601") from exc
    if parsed_time.tzinfo is None:
        raise EvidenceValidationError("measured_at must include a timezone")

    artifact_sha256 = _required_str(data, "artifact_sha256").lower()
    if len(artifact_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in artifact_sha256):
        raise EvidenceValidationError("artifact_sha256 must be a 64-character lowercase hex digest")

    metrics_data = data.get("metrics")
    if not isinstance(metrics_data, Mapping):
        raise EvidenceValidationError("metrics must be an object")

    return DeploymentEvidence(
        deployment_id=_required_str(data, "deployment_id"),
        repository=_required_str(data, "repository"),
        environment=environment,
        commit_sha=_required_str(data, "commit_sha"),
        artifact_sha256=artifact_sha256,
        measured_at=measured_at,
        source=source,
        metrics=metrics_from_mapping(metrics_data),
        canary_healthy=bool(data.get("canary_healthy", False)),
        observability_healthy=bool(data.get("observability_healthy", False)),
        rollback_ready=bool(data.get("rollback_ready", False)),
        production_regression=bool(data.get("production_regression", True)),
    )


def evaluate_deployment_evidence(
    evidence: DeploymentEvidence,
    policy: ProductionPolicy | None = None,
) -> dict[str, object]:
    metric_gate = evaluate_production_gate(evidence.metrics, policy)
    checks = {
        "metric_gate": metric_gate.passed,
        "canary_healthy": evidence.canary_healthy,
        "observability_healthy": evidence.observability_healthy,
        "rollback_ready": evidence.rollback_ready,
        "no_production_regression": not evidence.production_regression,
    }
    passed = all(checks.values())
    payload = {
        "schema_version": 1,
        "evidence": evidence.to_dict(),
        "metric_gate": metric_gate.to_dict(),
        "checks": checks,
        "passed": passed,
        "decision": "PASS" if passed else "BLOCK",
    }
    payload["proof_hash"] = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def verify_evidence_file(path: Path, policy: ProductionPolicy | None = None) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise EvidenceValidationError("evidence root must be a JSON object")
    return evaluate_deployment_evidence(parse_deployment_evidence(data), policy)

from __future__ import annotations

import pytest

from ci_failure_orchestrator.deployment_evidence import (
    EvidenceValidationError,
    evaluate_deployment_evidence,
    parse_deployment_evidence,
)


def _base() -> dict[str, object]:
    return {
        "deployment_id": "deploy-123",
        "repository": "Kozphy/ci-failure-orchestrator",
        "environment": "production",
        "commit_sha": "abc123",
        "artifact_sha256": "a" * 64,
        "measured_at": "2026-09-10T12:00:00+00:00",
        "source": "github-actions+otel",
        "metrics": {
            "repair_success_rate": 0.95,
            "regression_rate": 0.01,
            "p95_latency_seconds": 20.0,
            "cost_per_success_usd": 0.10,
            "critical_security_findings": 0,
        },
        "canary_healthy": True,
        "observability_healthy": True,
        "rollback_ready": True,
        "production_regression": False,
    }


def test_measured_production_evidence_passes() -> None:
    evidence = parse_deployment_evidence(_base())
    result = evaluate_deployment_evidence(evidence)
    assert result["passed"] is True
    assert result["decision"] == "PASS"
    assert len(result["proof_hash"]) == 64


@pytest.mark.parametrize("source", ["example", "fixture", "synthetic", "simulated", "mock"])
def test_non_measured_sources_are_rejected(source: str) -> None:
    data = _base()
    data["source"] = source
    with pytest.raises(EvidenceValidationError):
        parse_deployment_evidence(data)


def test_non_production_environment_is_rejected() -> None:
    data = _base()
    data["environment"] = "staging"
    with pytest.raises(EvidenceValidationError):
        parse_deployment_evidence(data)


def test_unhealthy_canary_blocks_production_success() -> None:
    data = _base()
    data["canary_healthy"] = False
    result = evaluate_deployment_evidence(parse_deployment_evidence(data))
    assert result["passed"] is False
    assert result["decision"] == "BLOCK"

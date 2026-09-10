# Measured Production Evidence

This repository separates **benchmark/simulated evidence** from **measured production evidence**.

A benchmark proves that a control can work under a reproducible test. It does **not** prove that a real production deployment was healthy. Production claims therefore require an independently supplied evidence document from the deployment and telemetry path.

## Required evidence

```json
{
  "deployment_id": "deploy-123",
  "repository": "Kozphy/ci-failure-orchestrator",
  "environment": "production",
  "commit_sha": "<deployed commit>",
  "artifact_sha256": "<64-char sha256>",
  "measured_at": "2026-09-10T12:00:00+00:00",
  "source": "github-actions+otel",
  "metrics": {
    "repair_success_rate": 0.95,
    "regression_rate": 0.01,
    "p95_latency_seconds": 20.0,
    "cost_per_success_usd": 0.10,
    "critical_security_findings": 0
  },
  "canary_healthy": true,
  "observability_healthy": true,
  "rollback_ready": true,
  "production_regression": false
}
```

## Fail-closed rules

The verifier blocks a production claim when any of the following is true:

- `source` is `example`, `fixture`, `synthetic`, `simulated`, or `mock`.
- `environment` is not `production`.
- `measured_at` is missing, invalid, or lacks a timezone.
- `artifact_sha256` is not a valid SHA-256 digest.
- the existing production metric gate fails.
- the canary is unhealthy.
- observability is unhealthy.
- rollback readiness is false.
- a production regression is detected.

## Evidence flow

```text
commit SHA
   ↓
build immutable artifact
   ↓
artifact SHA-256
   ↓
deploy
   ↓
canary
   ↓
telemetry / SLO measurement
   ↓
measured evidence JSON
   ↓
verify_deployment_evidence.py
   ↓
PASS / BLOCK
   ↓
tamper-evident proof_hash
```

## Important limitation

The repository can validate measured evidence, but it cannot manufacture real production telemetry. A genuine Level-6 production claim still requires a real deployment target and a collector that writes the evidence JSON from observed runtime data.

The workflow `.github/workflows/measured-production-evidence.yml` intentionally fails if that measured evidence is absent. It never falls back to `benchmark/production_metrics.example.json`.

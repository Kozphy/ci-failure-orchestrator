# Operational Evidence

The repository distinguishes **designed capability**, **simulated evidence**, and **measured production evidence**.

## Evidence maturity

```text
DESIGNED_CAPABILITY
  ↓
SIMULATED_VALIDATION
  ↓
MEASURED_STAGING_EVIDENCE
  ↓
MEASURED_PRODUCTION_EVIDENCE
  ↓
CONTROLLED_FAILURE_AND_RECOVERY_PROOF
```

A higher maturity state must never be inferred from a lower one.

## Required production deployment record

Each deployment record should include:

- deployment ID
- commit SHA
- immutable artifact digest
- environment
- start/completion timestamps
- deployment result
- canary result
- telemetry source
- rollback status
- recovery timestamp when applicable
- evidence/proof hash

## DORA-style delivery evidence

Deployment records can be aggregated into:

```text
DELIVERY_HEALTH =
DEPLOYMENT_FREQUENCY_MEASURED
AND LEAD_TIME_MEASURED
AND CHANGE_FAIL_RATE_MEASURED
AND RECOVERY_TIME_MEASURED_WHEN_FAILURES_EXIST
AND ROLLBACK_RATE_MEASURED
```

The implementation exposes deployment frequency, median deployment lead time, change fail rate, median recovery time, and rollback rate. These values are evidence signals; they are not claims of industry performance unless generated from real deployment history.

## Controlled rollback experiment

A production-readiness exercise should deliberately introduce a bounded canary failure and verify the full recovery loop:

```text
HEALTHY_VERSION
  ↓
BAD_CANARY
  ↓
TELEMETRY_DETECTS_DEGRADATION
  ↓
PROMOTION_BLOCKED
  ↓
ROLLBACK_TRIGGERED
  ↓
PREVIOUS_VERSION_RESTORED
  ↓
HEALTH_VERIFIED
  ↓
RECOVERY_TIME_RECORDED
```

The experiment must be isolated, reversible, authorized, and unable to impact unrelated workloads.

## Level-6 proof criterion

The repository should only describe itself as production-proven when the following are all backed by measured runtime evidence:

```text
LEVEL6_OPERATIONAL_PROOF =
MEASURED_PRODUCTION_EVIDENCE
AND IMMUTABLE_ARTIFACT_PROVENANCE
AND CANARY_RESULT_RECORDED
AND SLO_EVALUATED_FROM_RUNTIME_TELEMETRY
AND ROLLBACK_READY
AND FAILURE_RECOVERY_EXERCISED
AND RECOVERY_TIME_RECORDED
AND EVIDENCE_TAMPER_EVIDENT
```

Until then, the project should describe these controls as implemented or validated, not as proven at production scale.

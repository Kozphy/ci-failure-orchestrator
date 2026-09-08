# Observability and Production Rollout Gate

v1.1 adds a provider-neutral evidence payload, explicit production-readiness thresholds, and an optional OpenTelemetry bridge.

## What is measured

Each repair attempt can emit `RepairRunObservation` with repository, failure class, terminal action, retry count, evaluation score, latency, escalation, regression, and estimated cost fields.

The production gate aggregates a replay or benchmark window and blocks rollout when any configured threshold is violated:

- repair success rate
- false-repair rate
- regression rate
- p95 repair latency
- human-escalation rate

An empty evidence window always fails closed.

## OpenTelemetry

Install the optional integration with:

```bash
pip install -e '.[observability]'
```

`OpenTelemetryRecorder` emits:

- `ci_repair_runs`
- `ci_repair_latency_seconds`
- `ci_repair_human_escalations`
- `ci_repair_regressions`
- `ci.repair` trace spans

The core package remains dependency-free; exporters can be configured by the deployment environment.

## Production-proof workflow

```text
CI failure
  -> bounded repair loop
  -> independent evaluation
  -> RepairRunObservation
  -> benchmark/replay evidence window
  -> evaluate_production_gate
      -> PASS: eligible for policy/canary rollout
      -> FAIL: freeze automation / require human review
```

The gate is deliberately independent from the coding agent so an agent cannot approve its own production rollout.

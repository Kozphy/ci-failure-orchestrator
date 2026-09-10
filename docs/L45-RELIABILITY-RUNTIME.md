# L4.5 Reliability Runtime Upgrade

This upgrade moves the project from a capable CI repair orchestrator toward a provider-neutral autonomous reliability control plane.

## Architecture

```text
CI / Repository Event
        ↓
Durable Run Store
        ↓
Work Queue
        ↓
Diagnosis / Repair Agents
        ↓
AI Invocation Budget
        ↓
Policy / Approval Boundary
        ↓
Mandatory Evaluation Gate (EvalForge-compatible)
        ↓
PASS → Verified
FAIL → Dead Letter Queue
        ↓
Replay / Human RCA
        ↓
Telemetry + SLO Evidence
```

## What is implemented now

- `RunStore`, `WorkQueue`, `EvaluationGate`, and `TelemetrySink` protocols.
- In-memory queue for deterministic local tests.
- Mandatory evaluation before a candidate can become `verified`.
- DLQ routing and explicit replay.
- AI call/token/cost budget enforcement.
- Provider-neutral telemetry metrics.
- SLO snapshot for success rate, p95 latency, and DLQ rate.
- SQLite remains the dependency-free local durable store.

## Production adapters still required

The interfaces are intentionally ready for production adapters, but those adapters are not claimed as production evidence yet.

Recommended next implementations:

1. PostgreSQL `RunStore` with transactional leases and fencing tokens.
2. Redis Streams / SQS / Azure Service Bus / Kafka `WorkQueue`.
3. OpenTelemetry `TelemetrySink` with traces, metrics, and correlation IDs.
4. EvalForge remote/client adapter with quality, safety, regression, cost, and latency gates.
5. Signed human approval records and RBAC.
6. Canary deployment and automated rollback controller.
7. Failure-injection and long-running reliability benchmarks.

## Readiness definitions

```text
AGENT_RUN_SUCCESS =
TASK_COMPLETED
AND STATE_PERSISTED
AND AI_BUDGET_OK
AND POLICY_GATE_PASS
AND EVALUATION_GATE_PASS
AND SECURITY_GATE_PASS
AND REGRESSION_GATE_PASS
AND REQUIRED_APPROVALS_PASS

PRODUCTION_AUTONOMY_READY =
AGENT_RUN_SUCCESS
AND DISTRIBUTED_STORE_VERIFIED
AND DURABLE_QUEUE_VERIFIED
AND LEASE_FENCING_VERIFIED
AND DLQ_REPLAY_VERIFIED
AND OTEL_TRACE_COMPLETE
AND SLO_PASS
AND ERROR_BUDGET_OK
AND CANARY_HEALTHY
AND ROLLBACK_READY
AND FAILURE_RECOVERY_VERIFIED
AND PRODUCTION_EVIDENCE_COMPLETE
```

The repository should only claim `PRODUCTION_AUTONOMY_READY` when every condition above has measured evidence, not merely an implementation or architecture diagram.

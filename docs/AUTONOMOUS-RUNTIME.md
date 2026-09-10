# Autonomous Reliability Runtime

This layer upgrades the CI Failure Orchestrator from a repair loop into a resumable reliability control plane.

## Runtime contract

```text
CI event / incident
        ↓
Durable run state
        ↓
Scheduler lease
        ↓
Diagnosis / repair agent
        ↓
AI invocation budget
        ↓
Policy + approval gate
        ↓
Targeted/full validation
        ↓
PASS ───────────────→ complete + evidence
FAIL
        ↓
Retry budget
   ↓          ↓
 retry      exhausted
   ↓          ↓
backoff      DLQ
   ↓          ↓
resume       human/RCA
```

## New production primitives

`SQLiteRunStore` persists run state, AI usage, retry state, scheduling timestamps and worker leases. A process can restart and resume a run without reconstructing state from memory.

`InvocationBudget` provides hard limits for model calls, tokens and estimated dollar cost. Agent execution must reserve/record usage through the runtime instead of invoking models without a budget boundary.

`lease_due()` provides a minimal durable scheduler contract. Multiple workers cannot intentionally claim the same due item during the same SQLite transaction. The interface is designed so SQLite can later be replaced by Postgres plus a production queue.

`mark_retry()` applies bounded retry behavior and moves exhausted runs into a durable dead-letter queue rather than looping forever.

`approval_required()` makes production, destructive and high-risk changes explicit approval boundaries.

## Production migration path

SQLite is the local and portfolio reference implementation, not the final distributed backend. For multi-repository/fleet deployment, preserve the runtime API and replace the storage/queue layer with:

- PostgreSQL for durable run state and idempotency records.
- A durable queue such as SQS, RabbitMQ, Kafka or a workflow engine.
- Distributed leases with fencing tokens/idempotency keys.
- Central policy service and signed approval decisions.
- OpenTelemetry traces, metrics and structured audit events.
- Per-tenant and per-repository AI budgets.

## Readiness definition

```text
AGENT_RUN_SUCCESS =
TASK_COMPLETED
AND STATE_PERSISTED
AND RETRY_BUDGET_NOT_EXCEEDED
AND AI_BUDGET_OK
AND POLICY_GATE_PASS
AND EVALUATION_PASS
AND SECURITY_GATE_PASS
AND REGRESSION_GATE_PASS
AND REQUIRED_APPROVALS_PASS

PRODUCTION_AUTONOMY_READY =
AGENT_RUN_SUCCESS
AND CANARY_HEALTHY
AND ROLLBACK_READY
AND SLO_PASS
AND ERROR_BUDGET_OK
AND OBSERVABILITY_HEALTHY
AND AUDIT_EVIDENCE_COMPLETE
AND FAILURE_RECOVERY_VERIFIED
```

The repository should only claim the second level after publishing real deployment, failure-injection and recovery evidence.

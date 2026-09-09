# Bounded Autonomous Repair Loop

The control plane treats a coding agent as a replaceable worker, not as release authority.

```text
GitHub Actions failure
        ↓
FailedCheck normalization
        ↓
SupervisorPolicy
        ↓
AgentTask
        ↓
RepairIncident state machine
        ↓
DISPATCHED
        ↓
WorkerResult
        ↓
Independent verification
        ↓
GREEN | REVIEW_REQUIRED | RERUNNING | DENIED | ESCALATED
```

## State machine

```text
DETECTED
  ↓ plan
PLANNED
  ↓ dispatch
DISPATCHED
  ↓ safe patch
VERIFYING
  ├─ all gates + CI green → GREEN
  ├─ policy gate requires human → REVIEW_REQUIRED
  ├─ tests/CI still fail → RERUNNING → DETECTED
  └─ safety violation → DENIED

Protected/high-risk surface → ESCALATED
Critical or exhausted budget → DENIED
```

## Hard invariants

1. The worker cannot merge, approve, or weaken required checks.
2. Every attempt is bounded by retry, cost, time, file-count, and line-count budgets.
3. Regression, security, or test-weakening evidence fails closed.
4. Full regression remains independent of the repair worker.
5. A red rerun may retry only while the supervisor budget remains available.
6. Green CI is not sufficient if the policy gate requires human review.
7. Every lifecycle transition is recorded with a SHA-256 digest.

## Provider adapters

A Copilot, OpenAI, or other coding-agent adapter should consume `AgentTask` and return `WorkerResult`. The adapter should not receive release authority. This keeps orchestration policy provider-neutral and allows controlled agent replacement, benchmarking, and cost comparison.

## Production criterion

The autonomous path is considered production-capable only when benchmark evidence demonstrates acceptable repair success, false-repair rate, regression rate, P95 repair latency, retry behavior, and escalation precision. Passing unit tests proves control logic, not production effectiveness.

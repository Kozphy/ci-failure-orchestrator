# Agent execution foundation (Phases 2–10)

Foundation pipeline through **Phase 10 (Durable State + Audit)**.

See:

- [retry-budget.md](./retry-budget.md)
- [policy-gate.md](./policy-gate.md)
- [human-escalation.md](./human-escalation.md)
- [durable-state-and-audit.md](./durable-state-and-audit.md)

## Flow

```text
FailureEvent → … → Evaluation → Policy → (Approve|Reject|Escalate→AWAITING_HUMAN)
                         ↓
              StateStore + AuditStore + EvidenceStore
              (when artifacts_root is configured)
```

## Enable persistence

```python
AgentExecutionFoundation(artifacts_root=Path("artifacts"))
```

Without `artifacts_root`, runs remain in-memory (Phases 2–9 compatible).

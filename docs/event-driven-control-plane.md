# Event-Driven Repair Control Plane

## Target architecture

```text
GitHub / CI / Endpoint Events
           |
           v
       Event Bus
           |
           v
    Orchestrator
           |
           v
      Policy Engine
           |
           v
+----------+----------+
|          |          |
v          v          v
OpenClaw   Codex      Aider
|          |          |
+----------+----------+
           |
           v
     Candidate Store
           |
           v
      Verification
           |
           v
        Risk Score
           |
           v
       Approval Gate
           |
           v
        Draft PR
           |
           v
       Human Review
           |
           v
          Merge
```

## Authority model

The repair agents are **proposal workers**, not release authorities. They may inspect evidence and produce repair candidates, but they cannot approve their own work, bypass policy, merge protected branches, or directly deploy production changes.

The control plane owns routing, budgets, policy, independent verification, risk scoring, approval semantics, and delivery to a Draft PR.

## Components

- `event_bus.py`: typed GitHub/CI/endpoint event intake and a deterministic in-memory transport boundary. Production adapters can target Redis Streams, NATS, Kafka, or SQS.
- `event_control_plane.py`: multi-agent candidate collection, verification, risk scoring, selection, and Draft-PR publication boundary.
- existing `control_plane.py`: bounded repair execution core with classification, budgets, stopping conditions, evaluation, policy decisions, telemetry, and escalation.
- `CandidateStore`: persistence boundary for competing agent proposals. Replace the in-memory implementation with Postgres/object storage when durability is required.
- `Verifier`: independent test/security/regression gate. The verifier must not reuse the agent's own self-reported success as authoritative evidence.
- `RiskEngine`: normalized 0..1 risk score. Failed verification or high risk blocks promotion.
- `DraftPRPublisher`: delivery boundary. Production GitHub integration must create Draft PRs only; human review remains outside agent authority.

## Recommended production evolution

1. Add webhook adapters for GitHub Actions and endpoint telemetry.
2. Replace the in-memory event bus with a durable queue plus idempotency keys.
3. Persist candidates and verification evidence.
4. Add worker adapters for OpenClaw, Codex, and Aider with per-agent token/cost/time budgets.
5. Add retry/dead-letter handling for transport or worker failures.
6. Publish verification and risk evidence into the Draft PR body/checks.
7. Require protected-branch human approval before merge.

## Safety invariants

```text
AGENT_CAN_PROPOSE
AND AGENT_CANNOT_SELF_APPROVE
AND AGENT_CANNOT_BYPASS_POLICY
AND AGENT_CANNOT_MERGE_PROTECTED_BRANCH
AND VERIFICATION_IS_INDEPENDENT
AND HIGH_RISK_IS_BLOCKED
AND DELIVERY_DEFAULTS_TO_DRAFT_PR
```

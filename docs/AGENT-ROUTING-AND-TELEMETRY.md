# Agent Routing, Candidate Tournament, and Repair Telemetry

The CI Failure Orchestrator treats coding agents as interchangeable workers behind a policy-controlled boundary.

```text
Failed GitHub Actions check
        ↓
SupervisorDecision
        ↓
AgentTask
        ↓
Agent Router
 ├─ provider A / worker 1
 ├─ provider B / worker 2
 └─ local/custom worker
        ↓
Candidate patches
        ↓
Independent gates
 ├─ tests
 ├─ regression
 ├─ policy
 └─ security
        ↓
Candidate Tournament
        ↓
Best safe candidate
        ↓
Verification / rerun
        ↓
GREEN / REVIEW / ESCALATE
```

## Routing policy

Workers declare supported authorities, supported failure classes, maximum expected cost, and latency budget. The router filters workers before execution so an ineligible or over-budget provider is never dispatched.

Routing is provider-neutral: Copilot, OpenAI, or another worker can implement the same contract without receiving merge, approval, or release authority.

## Tournament policy

Safety is a hard constraint, not a score bonus. A candidate is eligible only when tests pass, no regression is detected, policy passes, and security passes.

Among safe candidates the current deterministic ordering is:

1. lower cost
2. lower latency
3. smaller patch
4. higher confidence
5. stable worker-name tie break

An unsafe candidate can never win even if it is cheaper, faster, or reports higher confidence.

## Repair effectiveness metrics

`RepairObservation` and `RepairMetrics` provide measurable evidence for autonomous repair performance:

- repair success rate
- false-repair rate
- mean cost per attempt
- cost per successful repair
- mean latency
- P95 repair latency
- mean attempts per incident
- provider-level comparisons

These metrics should be reported from executed repair attempts, not invented as production claims.

## Decision principle

> Route by capability and budget, reject unsafe candidates before ranking, select the smallest economically efficient safe repair, and measure whether autonomy actually improves reliability.

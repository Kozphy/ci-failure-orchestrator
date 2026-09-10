# Agent Supervisor Control Plane

This layer turns the project from a CI fixer into a **provider-agnostic repair supervisor**. External coding agents are workers; this repository remains the authority that decides whether they may act, how far they may go, and when autonomy must stop.

```text
GitHub Actions failure
        ↓
Failure classifier / causal RCA
        ↓
SupervisorPolicy
        ↓
Risk classification
 ┌──────────────┬──────────────────┬─────────────────┬─────────────────┐
 │ Low          │ Medium           │ High            │ Critical        │
 │ lint/type    │ app logic        │ workflow/IAM    │ secret/security │
 └──────┬───────┴────────┬─────────┴────────┬────────┴────────┬────────┘
        ↓                ↓                  ↓                 ↓
 autonomous patch   patch + review        RCA only           deny
        ↓                ↓                  ↓                 ↓
 targeted tests     targeted tests      human approval    security review
 full regression    full regression     full regression   human approval
 policy gate        human review        security gate
        ↓                ↓                  ↓
 evidence + budget accounting + escalation
```

## Separation of duties

The repair worker may be GitHub Copilot, another coding agent, or a custom executor. The worker never receives release authority merely because it produced a patch.

The supervisor owns:

- risk classification
- retry/cost/time/change budgets
- protected-path policy
- forbidden-action policy
- required verification gates
- escalation conditions
- machine-readable authority decisions

The worker owns only the task permitted by `RepairAuthority`.

## Authority model

| Risk | Example | Authority |
|---|---|---|
| Low | lint, formatting, typing, deterministic fixture | `AUTONOMOUS_PATCH` |
| Medium | application logic or unknown non-security failure | `PATCH_REQUIRES_REVIEW` |
| High | workflow, migration, auth, IAM, security, infra | `RCA_ONLY` |
| Critical | secrets, credentials, production-sensitive or security finding | `DENY` |

## Fail-closed conditions

Autonomous mutation stops immediately when any of these are true:

- regression detected
- test weakening detected
- retry budget exhausted
- changed-file budget exhausted
- changed-line budget exhausted
- cost budget exhausted
- elapsed-time budget exhausted
- critical path/security surface involved

These conditions cannot be overridden by the repair worker.

## Forbidden green-at-all-costs behavior

Every worker contract receives an explicit forbidden-action list. A repair must never become green by:

- deleting failing tests
- disabling required checks
- adding `continue-on-error` merely to hide failure
- lowering coverage without policy approval
- disabling security scanners
- exposing/modifying secrets
- force-merging around policy

## Suggested GitHub integration

A future GitHub adapter should translate the supervisor decision into worker behavior:

```text
AUTONOMOUS_PATCH
  → invoke coding agent
  → run targeted + full regression
  → attach evidence
  → policy gate

PATCH_REQUIRES_REVIEW
  → invoke coding agent
  → open/update PR
  → require human review

RCA_ONLY
  → collect logs + proposed patch/rationale
  → no mutation
  → request approval

DENY
  → freeze automated mutation
  → emit escalation evidence
```

## Metrics to add to the dashboard

The supervisor should expose:

- repairs attempted by risk level
- autonomous-repair success rate
- human-review rate
- deny/escalation rate
- retry-budget exhaustion rate
- test-weakening detections
- policy violations blocked
- cost per successful repair
- P50/P95 time-to-green
- rollback rate after autonomous repairs

## Design principle

> The agent is a worker, not the control plane. Green CI is an outcome; policy-compliant, evidence-backed repair is the objective.

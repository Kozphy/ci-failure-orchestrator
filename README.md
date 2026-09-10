# CI Failure Orchestrator

**v1.1 agentic CI reliability control plane** for dependency-aware diagnosis, bounded autonomous repair, multi-provider worker routing, candidate tournaments, persistent failure memory, independent evaluation, fleet policy, SLO/error-budget control, canary rollout, benchmarking, dashboard telemetry, human escalation, and tamper-evident production proof.

## Canonical success gates

The control plane uses three layered fail-closed predicates. A later stage can never report success unless every required condition in the previous stage is already satisfied.

```text
REPAIR_SUCCESS =
CI_GREEN
AND TARGETED_TESTS_PASS
AND FULL_REGRESSION_PASS
AND SECURITY_GATE_PASS
AND POLICY_GATE_PASS
AND NO_TEST_WEAKENING
AND NO_REGRESSION

RELEASE_READY =
REPAIR_SUCCESS
AND ARTIFACT_INTEGRITY_PASS
AND DEPENDENCY_GATE_PASS
AND DEPLOYMENT_VALIDATION_PASS
AND REQUIRED_APPROVALS_PASS
AND ROLLBACK_READY

PRODUCTION_SUCCESS =
RELEASE_READY
AND CANARY_HEALTHY
AND SLO_PASS
AND ERROR_BUDGET_OK
AND OBSERVABILITY_HEALTHY
AND NO_PRODUCTION_REGRESSION
```

These definitions are implemented as canonical code predicates. Agent self-report is never sufficient for success. Telemetry, benchmarks, release promotion, and production proof should consume these verified outcomes rather than inventing separate success definitions.

## Control-plane flow

```text
GitHub repositories
        ↓
Workflow runs / jobs / logs
        ↓
Failure Dependency Graph
        ↓
Root-cause classification + ranking
        ↓
Failure Memory Agent + SQLiteIncidentStore
        ↓
Memory-Aware Repair Planner
        ↓
SupervisorPolicy
        ↓
AgentTask contract
        ↓
Agent Router
 ├─ Copilot / coding agent
 ├─ OpenAI worker
 └─ local/custom worker
        ↓
Bounded Agent Executor
        ↓
Isolated Git Worktree / Sandbox
        ↓
Candidate patches
        ↓
Independent gates
 ├─ targeted tests
 ├─ full regression
 ├─ security
 └─ policy
        ↓
Candidate Tournament
        ↓
Best safe candidate
        ↓
Repair State Machine
        ↓
REPAIR_SUCCESS
        ↓
Artifact / dependency / deployment / approval / rollback gates
        ↓
RELEASE_READY
        ↓
Canary / SLO / error budget / observability / production regression gates
        ↓
PRODUCTION_SUCCESS
        ↓
Production proof
```

## Safety principle

Repair workers may propose changes, but they cannot approve their own release. Evaluation, regression checks, repository policy, release-readiness gates, production-health gates, canary health, fleet policy, SLOs, and human approval retain release authority.

Unsafe candidates can never win a provider tournament, and a green CI signal alone can never be promoted directly to release or production success.

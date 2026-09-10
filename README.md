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

## Operational evidence maturity

The repository distinguishes implementation from proof:

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

Example, fixture, synthetic, simulated, or mock metrics must never be promoted as measured production proof. The measured-production evidence gate requires provenance-bearing runtime evidence including a deployment ID, commit SHA, immutable artifact digest, telemetry source, canary health, observability health, rollback readiness, and regression status.

DORA-style operational metrics are computed from deployment history rather than declared manually:

```text
DELIVERY_HEALTH =
DEPLOYMENT_FREQUENCY_MEASURED
AND LEAD_TIME_MEASURED
AND CHANGE_FAIL_RATE_MEASURED
AND RECOVERY_TIME_MEASURED_WHEN_FAILURES_EXIST
AND ROLLBACK_RATE_MEASURED
```

A repository-level production claim is intentionally stricter:

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

Until those conditions are backed by real runtime measurements, the project describes the controls as implemented or validated rather than production-proven at scale. See `docs/operational-evidence.md`.

## Safety principle

Repair workers may propose changes, but they cannot approve their own release. Evaluation, regression checks, repository policy, release-readiness gates, production-health gates, canary health, fleet policy, SLOs, and human approval retain release authority.

Unsafe candidates can never win a provider tournament, and a green CI signal alone can never be promoted directly to release or production success.

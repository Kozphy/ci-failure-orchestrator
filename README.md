# Agent Reliability Harness

The toolkit uses AI only as a bounded diagnosis and repair-proposal layer.
Deterministic policy, remediation, verification, rollback, human approval, and
audit controls retain execution authority.

Evidence
  ↓
LLM Diagnosis
  ↓
Repair Proposal
  ↓
Policy
  ↓
Preview / Sandbox
  ↓
Verification
  ↓
Retry / Escalate
  ↓
Audit

Stage to source mapping (existing paths only):

- Evidence / deterministic diagnosis
  - `ci_failure_orchestrator/classifier.py`
  - `ci_failure_orchestrator/graph.py`
  - `ci_failure_orchestrator/ranker.py`
  - `ci_failure_orchestrator/causal.py`
- LLM diagnosis / repair proposal (bounded, provider-neutral)
  - `ci_failure_orchestrator/model_client.py`
  - `ci_failure_orchestrator/repair_proposal.py`
- Policy gate
  - `ci_failure_orchestrator/proposal_policy.py`
  - `ci_failure_orchestrator/policy.py`
  - `ci_failure_orchestrator/supervisor.py`
- Preview / sandbox / safe execution
  - `ci_failure_orchestrator/repair.py`
  - `ci_failure_orchestrator/patch_sandbox.py`
  - `ci_failure_orchestrator/repair_execution.py`
- Verification
  - `ci_failure_orchestrator/verification.py`
  - `ci_failure_orchestrator/repair_plan_evaluator.py`
- Retry / escalation
  - `ci_failure_orchestrator/escalation.py`
  - `ci_failure_orchestrator/agent_loop.py`
  - `ci_failure_orchestrator/repair_state_machine.py`
- Audit
  - `ci_failure_orchestrator/audit.py`
  - `ci_failure_orchestrator/evidence_signing.py`
  - `ci_failure_orchestrator/production_evidence.py`

The LLM proposes. The deterministic system verifies. The policy gate decides.
The human retains authority. The audit trail proves what happened.

## Demo

```bash
python -m ci_failure_orchestrator.agent_demo
python -m ci_failure_orchestrator.agent_demo --audit /tmp/agent_demo.audit.jsonl
```

The demo is non-destructive. It exercises the bounded harness with a deterministic
fixture model and emits an optional append-only, hash-chained audit record.

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

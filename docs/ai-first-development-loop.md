# AI-First Autonomous Development Loop

This document extends the CI Failure Orchestrator into a control plane for fast, bounded AI-first software delivery.

## Goal

Minimize human hand-offs without allowing an AI worker to approve its own work.

```text
Issue / executable spec
        ↓
Risk + scope classification
        ↓
Coding Agent
        ↓
Implementation + tests
        ↓
Local deterministic verification
        ↓
Self-repair loop (bounded)
        ↓
Commit / Draft PR
        ↓
GitHub CI
        ↓
Review Aggregator
 ├─ AI review
 ├─ static analysis
 ├─ security analysis
 └─ dependency analysis
        ↓
Independent Verifier
        ↓
Policy Engine
        ↓
REPAIR_SUCCESS
        ↓
Release gates
        ↓
RELEASE_READY
        ↓
Canary deployment
        ↓
Runtime telemetry / SLO
        ↓
PRODUCTION_SUCCESS
        ↓
Evidence + learning memory
```

## Human / AI responsibility boundary

The coding agent may own implementation mechanics: repository inspection, edits, tests, documentation, targeted repair, and draft-PR preparation. It does **not** own release authority.

Humans retain authority for high-impact requirements, architecture trade-offs, privileged/security-sensitive changes, irreversible operations, exceptions to policy, and final approval where policy requires it.

## Executable task contract

Every autonomous task should be normalized before execution:

```text
AgentTask =
TASK_ID
+ GOAL
+ ACCEPTANCE_CRITERIA
+ ALLOWED_PATHS
+ FORBIDDEN_PATHS
+ RISK_CLASS
+ TEST_PLAN
+ TOKEN_BUDGET
+ TIME_BUDGET
+ RETRY_BUDGET
+ REQUIRED_GATES
+ ESCALATION_POLICY
```

An ambiguous task fails closed or escalates instead of granting the worker unlimited repository scope.

## Bounded autonomous repair

```text
while budget_remaining:
    inspect evidence
    propose minimal patch
    run targeted checks
    if targeted checks fail:
        diagnose and retry
        continue
    run required deterministic gates
    if all required gates pass:
        submit candidate to independent verifier
        break

if budget exhausted:
    escalate with evidence
```

The repair worker cannot change the definition of success, silently delete failing tests, reduce coverage thresholds, disable security checks, or modify policy solely to make its own candidate pass.

## Fast path vs guarded path

Low-risk changes can use a fast path:

```text
LOW_RISK_FAST_PATH =
SCOPE_BOUNDED
AND TARGETED_TESTS_PASS
AND FULL_REGRESSION_PASS
AND STATIC_ANALYSIS_PASS
AND SECURITY_GATE_PASS
AND POLICY_GATE_PASS
AND INDEPENDENT_VERIFICATION_PASS
```

High-risk changes require explicit approval:

```text
HIGH_RISK_RELEASE =
LOW_RISK_FAST_PATH
AND REQUIRED_HUMAN_APPROVAL
AND ROLLBACK_READY
AND DEPLOYMENT_VALIDATION_PASS
```

Examples of high-risk areas include authentication/authorization, secrets, destructive data migrations, billing, production infrastructure, policy definitions, release controls, and changes that broaden agent permissions.

## Independent verification

The verifier must be logically independent from the worker that produced the patch. It should consume the candidate diff and evidence rather than trusting the worker's narrative.

```text
INDEPENDENT_VERIFICATION_PASS =
DIFF_WITHIN_SCOPE
AND ACCEPTANCE_CRITERIA_VERIFIED
AND TEST_INTEGRITY_PASS
AND NO_TEST_WEAKENING
AND NO_POLICY_BYPASS
AND SECURITY_EVIDENCE_VALID
AND REGRESSION_EVIDENCE_VALID
```

## Draft PR as the default autonomous boundary

A useful default is to allow an agent to autonomously reach a draft PR, while keeping promotion governed:

```text
SPEC
 → AGENT IMPLEMENTATION
 → SELF-REPAIR
 → LOCAL VERIFICATION
 → DRAFT PR
 → CI / REVIEW / POLICY
 → HUMAN OR POLICY APPROVAL
 → MERGE
```

This preserves speed while creating an inspectable checkpoint with a diff, test evidence, provenance, and rollback point.

## Feedback and memory

After each run, store only evidence-backed learning:

```text
failure signature
+ root cause
+ attempted repair
+ verification result
+ final outcome
+ cost / latency
+ rollback or incident result
```

Future planners may use this memory to rank repair strategies, but historical success never overrides current verification.

## Metrics

Measure whether autonomy is actually improving delivery:

- time from failure to diagnosis
- time from diagnosis to verified candidate
- autonomous repair success rate
- retries per successful repair
- human interventions per task
- false-green / escaped-regression rate
- rollback rate
- token and compute cost per verified repair
- PR lead time
- change failure rate
- recovery time

Optimize for **verified throughput**, not generated lines of code.

## Core invariant

```text
AI_GENERATED != TRUSTED

TRUSTED_CHANGE =
BOUNDED_AGENT_EXECUTION
AND REPAIR_SUCCESS
AND INDEPENDENT_VERIFICATION_PASS
AND REQUIRED_APPROVALS_PASS
```

The fastest safe loop is therefore not “AI writes everything and merges everything.” It is “AI performs as much bounded implementation and repair as possible while deterministic and independent controls make promotion decisions.”

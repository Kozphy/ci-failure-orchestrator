# AI Reliability Control Plane — Project Specification

## 1. Purpose

This project aims to build a measurable, reproducible, and safety-aware control plane for AI systems and CI/CD reliability workflows.

The system should combine:

- AI evaluation
- regression detection
- failure classification
- repair proposal generation
- sandbox execution
- selective verification
- retry budgets
- policy gates
- canary rollout
- human escalation
- audit evidence
- reliability / SLO reporting

The primary goal is not to maximise feature count.

The primary goal is to demonstrate:

- strong systems thinking
- measurable reliability engineering
- reproducible AI evaluation
- safe automation
- governance
- observability
- production-readiness
- research-quality evidence

---

## 2. Existing Repositories

### EvalForge

Primary responsibility:

AI evaluation and regression detection.

Core concepts:

- golden datasets
- deterministic graders
- LLM-as-judge
- human review
- regression detection
- evaluation gates
- hashed evidence
- reproducibility

### ci-failure-orchestrator

Primary responsibility:

Failure orchestration and controlled recovery.

Core concepts:

- failure classification
- root-cause ranking
- repair proposal
- sandbox execution
- selective verification
- retry budgets
- escalation
- audit logging
- self-healing workflows
- reliability metrics

---

## 3. Target System

The target logical flow is:

```text
AI Agent / CI System
        ↓
Observation / Evaluation
        ↓
Failure or Regression Detection
        ↓
Failure Classification
        ↓
Root-Cause Ranking
        ↓
Repair Proposal
        ↓
Sandbox Execution
        ↓
Verification / Evaluation
        ↓
Retry Budget
        ↓
Policy Gate
        ↓
Canary Rollout
        ↓
Human Escalation
        ↓
Audit Evidence
        ↓
SLO / Reliability Reporting
```

EvalForge should act primarily as the evaluation layer.

ci-failure-orchestrator should act primarily as the orchestration and reliability-control layer.

Avoid unnecessary duplication between the two systems.

---

## 4. Core Architectural Principle

The architecture should separate:

```text
Observation
Decision
Execution
Evaluation
Policy
Escalation
Evidence
```

No single agent or module should have unrestricted authority over the entire lifecycle.

In particular:

```text
Proposal != Permission
```

An AI-generated repair proposal must not automatically imply permission to execute or deploy it.

---

## 5. Normalised Failure Event

All major reliability events should converge on a shared logical schema.

Recommended fields:

```text
event_id
timestamp
source
system_type
component
failure_class
severity
confidence

evaluation_id
dataset_version
model_version

root_cause_candidates
proposed_action

retry_count
retry_budget

policy_version
policy_decision
policy_reason

sandbox_status
verification_status
canary_status

human_approval_required
human_approval_status

final_outcome

input_hash
output_hash
evidence_hash
```

The exact implementation may differ, but the semantic meaning should remain stable.

Prefer typed schemas.

---

## 6. Failure Taxonomy

The system should support explicit failure classes.

Initial taxonomy:

```text
dependency_failure
flaky_test
timeout
network_failure
schema_drift
tool_failure

malformed_model_output
hallucination
low_confidence_output
evaluation_regression

policy_violation
unsafe_action
budget_exhaustion

verification_failure
canary_failure
unknown_failure
```

Avoid creating dozens of overlapping classes without evidence that they are needed.

---

## 7. Failure Injection

The project must include reproducible failure injection.

Every injected scenario should contain:

```text
scenario_id
seed
expected_failure_class
input
expected_behaviour
expected_policy_decision
expected_recovery_state
```

Initial scenarios should include:

- flaky test
- dependency failure
- timeout
- network failure
- malformed model response
- hallucinated answer
- policy violation
- schema drift
- tool-call failure
- low-confidence evaluation
- unsafe repair proposal
- corrupted evidence

Failure injection must be deterministic where practical.

---

## 8. Evaluation and Benchmarking

Every major architectural improvement should be benchmarkable.

Core metrics:

```text
classification_accuracy
precision
recall
f1

false_positive_rate
false_negative_rate

regression_detection_rate

recovery_rate
unsafe_remediation_rate

mean_retry_count
retry_budget_exhaustion_rate

MTTD
MTTR

latency_p50
latency_p95

cost_per_incident

policy_block_rate
human_escalation_rate
```

Where appropriate, calculate confidence intervals.

Do not report invented metrics.

If a metric cannot yet be measured, mark it clearly as:

```text
TODO: requires benchmark implementation
```

---

## 9. Baselines

Benchmarking must compare the full system against simpler approaches.

Minimum baselines:

### Baseline A

No automated recovery.

### Baseline B

Blind retry only.

### Baseline C

AI-generated repair without policy gate.

### Baseline D

Evaluation gate without retry budget.

### Full System

```text
Evaluation
+ Failure Classification
+ Repair Proposal
+ Sandbox
+ Verification
+ Retry Budget
+ Policy Gate
+ Canary
+ Human Escalation
```

The benchmark should show whether each layer actually provides measurable value.

---

## 10. Ablation Testing

Where practical, remove one component at a time.

Examples:

```text
Full system - policy gate
Full system - retry budget
Full system - human escalation
Full system - evaluation gate
Full system - canary
```

Compare:

- recovery rate
- unsafe remediation
- cost
- latency
- false positives
- escalation rate

The goal is to determine which controls materially improve outcomes.

---

## 11. Policy Layer

Policies must be:

- explicit
- versioned
- deterministic
- testable
- auditable

Potential policies:

```text
maximum_retry_count
maximum_cost_budget
minimum_confidence_threshold

allowed_command_scope
allowed_file_scope

protected_paths
prohibited_commands

required_test_suite

mandatory_human_approval_conditions

canary_required_conditions

automatic_recovery_severity_limit
```

An AI agent must not be able to bypass policy directly.

---

## 12. Retry Budget

Retries must be bounded.

A retry policy should consider:

```text
attempt_count
failure_class
previous_outcomes
estimated_cost
elapsed_time
confidence
severity
```

The system should distinguish between:

```text
retryable_failure
non_retryable_failure
requires_escalation
```

Infinite retries are prohibited.

---

## 13. Sandbox Execution

Potential remediation should be executed in an isolated environment whenever practical.

The sandbox should capture:

```text
commands
files_changed
tests_run
exit_codes
logs
duration
resource_usage
```

The sandbox must produce evidence sufficient for later verification.

---

## 14. Verification

A remediation is not considered successful merely because execution completed.

Verification may include:

- unit tests
- integration tests
- targeted regression tests
- evaluation datasets
- policy validation
- static checks
- behavioural checks

The system must distinguish:

```text
execution_success
```

from:

```text
verified_success
```

---

## 15. Canary Rollout

Changes with production impact should support limited rollout.

Logical sequence:

```text
Proposal
→ Sandbox
→ Evaluation
→ Policy Gate
→ Canary
→ Verification
→ Expand or Roll Back
```

Capture:

```text
canary_scope
canary_duration
success_criteria
rollback_criteria
post_change_metrics
rollback_reason
```

---

## 16. Human Escalation

Automation should escalate rather than continue autonomously when risk exceeds configured limits.

Escalation triggers may include:

```text
low confidence
high severity
retry budget exhausted
policy ambiguity
repeated verification failure
protected resource modification
unsafe command proposal
cost threshold exceeded
unknown failure class
```

The human should receive:

```text
what failed
why the system thinks it failed
what was attempted
what evidence exists
what action is recommended
what risks remain
```

---

## 17. Audit Evidence

Important decisions must produce append-only structured evidence.

Recommended audit fields:

```text
event_id
timestamp
actor
action
reason

input_hash
output_hash

model_version
dataset_version
policy_version

policy_decision
approval_state

verification_result
final_outcome
```

Tamper-evident hashing should be used where practical.

---

## 18. Reliability and SLO Reporting

The backend should expose metrics suitable for dashboards.

Important metrics:

```text
incidents_by_failure_class
recovery_rate
automatic_recovery_rate
human_escalation_rate

policy_block_rate
unsafe_proposal_rate

retry_budget_exhaustion_rate

MTTD
MTTR

evaluation_regression_rate

cost_per_incident

SLO_compliance
```

Do not prioritise visual dashboards before the metrics are reliable.

---

## 19. Observability

Important transitions should emit structured logs.

Prefer structured events over human-only log strings.

Each workflow should be traceable through:

```text
trace_id
event_id
evaluation_id
repair_id
policy_decision_id
deployment_id
```

The user should be able to reconstruct why a decision happened.

---

## 20. Testing Strategy

Testing should include:

### Unit tests

For deterministic components.

### Integration tests

For interactions between:

- evaluation
- classifier
- policy
- retry
- sandbox
- verification

### Failure-injection tests

For controlled resilience testing.

### Regression tests

For known past failures.

### Property tests

Where useful for invariant-heavy logic.

Important invariants:

```text
retry_count <= retry_budget

policy_denied => execution_not_allowed

human_approval_required
AND
human_approval_missing
=> production_execution_not_allowed

verification_failed
=> success_not_recorded
```

---

## 21. Research Questions

The project should be capable of answering:

### RQ1

How accurately can the system classify AI and CI failures?

### RQ2

Does evaluation-gated remediation reduce MTTR without increasing unsafe changes?

### RQ3

How does retry-budget policy affect:

- recovery rate
- cost
- latency
- false remediation

### RQ4

When does human escalation outperform autonomous remediation?

### RQ5

Which control-plane components provide the largest measurable reliability improvement?

---

## 22. Research Report

Maintain:

```text
docs/research-report.md
```

Recommended structure:

```text
Abstract

Motivation

Research Questions

Architecture

Failure Taxonomy

Dataset / Failure Corpus

Experimental Setup

Baselines

Metrics

Results

Ablation Study

Failure Analysis

Threats to Validity

Limitations

Reproducibility

Future Work
```

All claims should be tied to reproducible evidence.

---

## 23. Portfolio Case Study

Maintain:

```text
docs/case-study.md
```

Format:

```text
Problem
↓
Constraints
↓
System Design
↓
Experiment
↓
Results
↓
Failure Analysis
↓
Business Impact
```

Prefer measurable statements.

Example:

```text
Across 1,200 injected failure scenarios,
the classifier achieved an F1 score of X.
```

Never fabricate results.

---

## 24. README Requirements

The README should allow a hiring manager to understand the project in approximately one minute.

Recommended structure:

```text
One-line positioning

Problem

Architecture

How it works

Key capabilities

Benchmark results

Safety model

Example incident

Quickstart

Reproducibility

Research report

Limitations
```

Recommended positioning:

> An evaluation-gated reliability control plane for AI agents and CI systems.

Avoid unsupported language such as:

- world-class
- revolutionary
- enterprise-grade
- production-proven
- industry-leading

unless evidence supports it.

---

## 25. Non-Goals

Do not prioritise:

- rewriting Python in another language merely for prestige
- microservices without operational need
- Kubernetes without deployment justification
- distributed systems without scale requirements
- excessive abstractions
- dozens of agents
- decorative dashboards
- speculative features
- fake benchmark results
- fake customers
- fake production deployments

Complexity must be justified.

---

## 26. Engineering Rules

All coding agents must follow these rules:

```text
Preserve working code.

Do not modify unrelated modules.

Prefer incremental changes.

Add tests before risky refactors.

Use typed interfaces for important contracts.

Keep evaluation reproducible.

Keep policy decisions deterministic.

Keep audit evidence structured.

Do not silently swallow failures.

Do not introduce new frameworks without justification.

Do not add architecture purely to look sophisticated.

Do not invent benchmark numbers.

Do not claim production readiness without evidence.
```

---

## 27. Change Template

For every significant change, the coding agent should report:

```text
Problem

Why this change is needed

Files affected

Design

Implementation

Tests

Benchmark impact

Risks

Rollback strategy

Definition of Done
```

---

## 28. Definition of Done

A task is not complete merely because code exists.

A meaningful task should normally satisfy:

```text
Code implemented
+
Tests passing
+
Expected failure behaviour tested
+
Relevant metrics captured
+
Documentation updated
+
No policy regression
+
No unrelated changes
```

For benchmark-related work:

```text
Reproducible command
+
Machine-readable output
+
Baseline comparison
+
Documented methodology
```

---

## 29. Priority Order

When deciding what to work on, use this ordering:

```text
1. Correctness
2. Safety
3. Benchmark evidence
4. Production evidence
5. Reliability
6. Observability
7. Governance
8. Developer experience
9. Architecture elegance
10. New features
```

---

## 30. Initial Roadmap

### P0 — Evidence Foundation

Build first:

- common failure schema
- failure taxonomy
- reproducible failure injection
- benchmark runner
- baseline experiments
- structured evidence output

### P1 — Reliability Control

Then build:

- retry budgets
- policy engine
- sandbox verification
- escalation logic
- canary workflow

### P2 — Production Proof

Then pursue:

- real external repositories
- real users
- real incidents
- deployment evidence
- measurable operational outcomes

---

## 31. Agent Instructions

When an AI coding agent reads this specification:

Do not immediately implement the entire roadmap.

First:

1. Inspect the repository.
2. Compare the existing implementation against this specification.
3. Identify what already exists.
4. Identify missing pieces.
5. Identify duplicated or overengineered pieces.
6. Propose the smallest useful next change.

Then return:

```text
Current State

What Already Exists

Critical Gaps

Unnecessary Complexity

Top 5 Next Actions

Recommended First Issue

Acceptance Criteria
```

Do not modify code until explicitly instructed.

---

## 32. North-Star Goal

The final project should make it possible to demonstrate:

> An AI or CI system failed.

> The system detected and classified the failure.

> It proposed a bounded remediation.

> The remediation was tested in isolation.

> Evaluation determined whether it improved the system.

> Policy determined whether it was safe.

> Retry budgets prevented uncontrolled loops.

> High-risk cases escalated to a human.

> Every important decision generated auditable evidence.

> The final result was measured against a baseline.

That is the standard this project should optimise toward.
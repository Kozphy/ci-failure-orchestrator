# CI Failure Orchestrator

Dependency-aware **causal CI/CD/CT failure orchestration**. Instead of fixing the latest red job, it asks which failure most plausibly caused the others and verifies that hypothesis with the smallest useful rerun plan.

## Agentic repair control plane

```text
GitHub Actions jobs + logs
          ↓
   Error classification
          ↓
      Pipeline DAG
          ↓
  Causal edge inference
          ↓
 Root-cause ranking
          ↓
 Repair Planner Agent
          ↓
 Multiple Coding Agents
          ↓
 Bounded Agent Executor
          ↓
 Independent Evaluator
          ↓
 Candidate Tournament
          ↓
 Cost / Latency / Risk scoring
          ↓
 Policy Gate / Human Escalation
          ↓
 Canary / Rollback boundary
          ↓
 Production Evidence
```

A CI run may show `Type Check ❌ → Unit Test ❌ → Integration Test ❌ → Deploy ❌`. The visible deploy failure can be downstream noise. The orchestrator ranks the earliest causal failure, constrains the repair scope, lets multiple agents propose bounded candidates, evaluates them independently, chooses the best admissible candidate, and stops unsafe or unproductive repair loops.

## Features

- Pipeline dependency DAG with cycle validation
- Error classification and confidence
- Root-cause ranking based on upstream impact, causal rules, depth, severity, and criticality
- Causal failure graph with evidence and edge confidence
- GitHub Actions job/log ingestion from normalized API payloads
- Repair Planner Agent with bounded hypotheses, risk classification, rollback intent, and human-approval gating
- Provider-neutral Coding Agent protocol for future Cursor / Codex / Claude / Orca adapters
- Coding Agent Executor that rejects out-of-scope or empty patches
- Independent evaluation contract for targeted checks and full regression
- Retry budget and explicit stopping conditions
- Immediate rollback/escalation path when regression is detected
- Multi-agent Repair Tournament with utility-based candidate selection
- Cost, latency, confidence, evaluation, and risk-aware candidate scoring
- Final Policy Gate with automated thresholds and human-approval fallback
- Hashable Production Evidence record for the selected candidate and release decision
- Selective verification planner: root stage → predicted downstream failures → full pipeline
- Retry/escalation primitives and hash-chained audit log
- Benchmark metrics for Top-1/Top-3 RCA accuracy and cascade elimination

## Repair Planner Agent

`DeterministicRepairPlanner` converts a ranked root-cause hypothesis into a constrained `RepairPlan` before any coding agent is allowed to edit source code.

A plan contains:

```text
root stage
hypothesis
candidate target files
proposed minimal change
risk level
human approval requirement
rollback strategy
verification sequence
```

High-risk and unknown failure classes fail safe by requiring human approval.

## Coding Agent Executor

`CodingAgentExecutor` is the policy boundary between planning and code mutation. An agent receives a `RepairPlan` and returns a `PatchProposal`. The executor rejects a proposal when it edits files outside the approved target scope, returns an empty patch, or attempts to execute a high-risk plan without approval.

The interface is provider-neutral so external coding systems can be added as adapters without coupling orchestration policy to a single model vendor.

## Evaluator-driven repair loop

`AgentRepairLoop` runs bounded repair attempts using an independent evaluator rather than trusting the coding agent to declare success.

```text
plan
 ↓
agent patch proposal
 ↓
scope / approval checks
 ↓
targeted evaluation
 ↓
regression evaluation
 ↓
PASS  → READY_FOR_POLICY_GATE
FAIL  → retry while budget remains
REGRESSION → ROLLBACK_AND_ESCALATE
BUDGET EXHAUSTED → ESCALATE_HUMAN
```

This prevents infinite token-burning repair loops and makes stopping behavior reproducible and testable.

## Multi-agent Repair Tournament

`RepairTournament` runs multiple provider-neutral coding agents through the same execution boundary and independent evaluator. Candidates are admitted only when targeted checks and regression evaluation pass and risk remains below the automatic threshold.

Candidate utility is based on:

```text
evaluation score
- cost penalty
- latency penalty
- risk penalty
```

This means an expensive or slow patch does not automatically beat a cheaper equivalent patch, and a high-scoring patch with regression risk is still rejected.

## Policy Gate and Production Evidence

`RepairPolicyGate` is a separate decision boundary after candidate selection. It can return:

```text
READY_FOR_CANARY
HUMAN_APPROVAL_REQUIRED
BLOCK
ESCALATE_HUMAN
```

The gate checks risk, cost, latency, and independent evaluation rather than trusting the winning agent. `build_production_evidence()` then records the root stage, selected agent, evaluation score, risk, cost, latency, candidate count, policy action, and a deterministic SHA-256 evidence hash.

## Quick start

```bash
python -m pip install -e ".[dev]"
pytest
```

```bash
ci-orchestrator analyze \
  --jobs examples/github_jobs.json \
  --logs examples/github_logs.json \
  --audit audit.jsonl
```

## Evaluation targets

- Top-1 Root Cause Accuracy
- Top-3 Root Cause Accuracy
- False Root-Cause Rate
- Cascading Failures Eliminated
- Mean retries before resolution
- MTTR reduction
- Verification cost
- Auto-fix success rate
- Regression escape rate
- Human escalation rate
- Repair attempts per resolved incident
- Candidate win rate by agent/provider
- Cost per resolved incident
- P50 / P95 repair latency
- Policy override rate

## Roadmap

**v0.3** — direct GitHub API collector for workflow runs/jobs/logs and workflow-DAG reconstruction.

**v0.4** — real coding-agent adapters, affected-test selection, rollback execution, canary integration, cost/latency telemetry collection, and human approval workflows.

**v0.5** — multi-agent candidate tournament, utility scoring, policy gate, and production evidence. *(core contracts implemented)*

**v1.0** — reproducible CI-failure benchmark suite, learned ranking calibration, dashboard, production policy controls, real canary/rollback execution, cross-provider agent benchmarking, and signed evidence bundles.

## Design principle

> Fix the earliest causal failure, constrain every repair, compare alternatives with independent evidence, and escalate when policy confidence is insufficient.

# CI Failure Orchestrator

Dependency-aware **causal CI/CD/CT failure orchestration**. Instead of fixing the latest red job, it asks which failure most plausibly caused the others and verifies that hypothesis with the smallest useful rerun plan.

## Agentic repair control plane

```text
GitHub Actions run / jobs / logs
          ↓
   Error classification
          ↓
      Pipeline DAG
          ↓
  Causal edge inference
          ↓
 Root-cause ranking
          ↓
 Failure Memory Agent
   ↙ retrieve   ↘ remember outcome
          ↓
 Memory-Aware Repair Planner
          ↓
 Multiple Coding Agents
          ↓
 CLI / provider adapters
          ↓
 Bounded Agent Executor
          ↓
 Isolated Git Worktree
          ↓
 Affected-test selection
          ↓
 Targeted Test Runner
          ↓
 Independent Evaluator
          ↓
 Candidate Tournament
          ↓
 Cost / Latency / Risk scoring
          ↓
 Policy Gate / Human Escalation
          ↓
 Canary Controller
          ↓
 Automatic Rollback boundary
          ↓
 Signed Production Evidence
```

A CI run may show `Type Check ❌ → Unit Test ❌ → Integration Test ❌ → Deploy ❌`. The visible deploy failure can be downstream noise. The orchestrator ranks the earliest causal failure, retrieves similar historical incidents, constrains the repair scope, lets multiple agents propose bounded candidates, evaluates them independently, chooses the best admissible candidate, and stops unsafe or unproductive repair loops.

## Features

- Pipeline dependency DAG with cycle validation
- Error classification and confidence
- Root-cause ranking based on upstream impact, causal rules, depth, severity, and criticality
- Causal failure graph with evidence and edge confidence
- Failure Memory Agent with structured incident records and similarity retrieval
- Persistent SQLite incident store with upsert and reopen semantics
- Memory-aware planner that adds bounded historical repair context without granting memory execution authority
- Historical successful/failed patch outcomes, retries, cost, latency, affected tests, and regression evidence
- GitHub Actions failed-job/log collector abstraction
- Repair Planner Agent with bounded hypotheses, risk classification, rollback intent, and human-approval gating
- Provider-neutral Coding Agent protocol
- CLI coding-agent adapter using JSON over stdin/stdout with no shell invocation
- Coding Agent Executor that rejects out-of-scope or empty patches
- Isolated Git worktree per repair candidate with patch apply/reset/cleanup
- Conservative affected-test selection with explicit mapping hooks and full-suite fallback
- Executable targeted-test and full-regression pytest runner
- Independent evaluation contract for targeted checks and full regression
- Retry budget and explicit stopping conditions
- Immediate rollback/escalation path when regression is detected
- Multi-agent Repair Tournament with utility-based candidate selection
- Cost, latency, confidence, evaluation, and risk-aware candidate scoring
- Final Policy Gate with automated thresholds and human-approval fallback
- Canary deploy/health/rollback controller boundary
- Hashable Production Evidence record for the selected candidate and release decision
- HMAC-SHA256 signed evidence envelopes with tamper verification
- Retry/escalation primitives and hash-chained audit log

## Failure Memory Agent

`FailureMemoryAgent` adds learning across incidents without giving memory any repair or release authority. Each `IncidentMemory` can record an error signature, failure class, root stage, changed files, successful and failed repair summaries, affected tests, retries, cost, latency, regression outcome, and metadata.

Retrieval uses a deterministic weighted similarity over error-signature tokens, failure class, root stage, and changed-file overlap. Historical regressions remain visible and are never counted as successful repair evidence.

`SQLiteIncidentStore` persists those incidents using Python's standard-library `sqlite3`, so memory survives process restarts without introducing another runtime dependency. The `IncidentStore` protocol remains unchanged, so SQLite can later be swapped for Postgres or a vector-backed implementation.

## Memory-Aware Repair Planner

`MemoryAwareRepairPlanner` decorates the deterministic planner. It retrieves a bounded set of similar incidents and records match count, successful-match count, top similarity, and historical regression count in plan metadata.

Only historical repairs that succeeded **without a recorded regression** are appended as advisory repair evidence. Regression-producing historical fixes remain visible in metadata but are never promoted into the proposed change.

```text
new failure
    ↓
MemoryQuery
    ↓
SQLite / IncidentStore
    ↓
retrieve top-K similar incidents
    ↓
separate successful evidence from regression history
    ↓
Memory-Aware Repair Planner
    ↓
bounded RepairPlan
```

## v0.7 execution layer

`GitHubActionsCollector` normalizes failed/cancelled/timed-out jobs and logs. `IsolatedGitWorkspace` creates a temporary worktree per candidate. `TargetedTestRunner` executes selected tests and full regression with timeout handling. `CanaryController` separates deploy, health-check, and rollback hooks.

## Real coding-agent adapter contract

`CommandCodingAgent` serializes an approved `RepairPlan` to JSON over stdin and expects one JSON patch proposal on stdout. It uses explicit argv with `shell=False`, keeping wrappers for Cursor, Codex, Claude, Orca, or other coding-agent CLIs provider-neutral.

## Safety properties

```text
memory suggests evidence (never authority)
      ↓
agent proposes patch
      ↓
approved file scope?
      ↓
human approval required?
      ↓
apply only in isolated worktree
      ↓
targeted tests + full regression
      ↓
tournament + policy
      ↓
canary
      ↓
healthy? ── no ──> rollback
      ↓ yes
signed evidence + remember outcome
```

The coding agent cannot select arbitrary files, declare itself successful, bypass regression checks, release itself, or retry indefinitely.

## Quick start

```bash
python -m pip install -e ".[dev]"
pytest
```

## Evaluation targets

- Top-1 / Top-3 Root Cause Accuracy
- False Root-Cause Rate
- Cascading Failures Eliminated
- Memory retrieval precision@K / success lift
- Historical-regression contamination rate
- Mean retries before resolution
- MTTR reduction
- Verification cost
- Auto-fix success rate
- Regression escape rate
- Human escalation rate
- Candidate win rate by agent/provider
- Cost per resolved incident
- P50 / P95 repair latency
- Targeted-test precision / recall
- Evidence signature verification rate
- Canary success rate
- Rollback success rate

## Roadmap

**v0.4** — bounded repair planner/executor/evaluator loop with retry and escalation. *(implemented)*

**v0.5** — multi-agent tournament, utility scoring, policy gate, and production evidence. *(implemented)*

**v0.6** — CLI coding-agent adapter, telemetry, affected-test hooks, and signed evidence. *(implemented)*

**v0.7** — GitHub Actions collector, isolated worktrees, executable tests, canary and rollback hooks. *(implemented)*

**v0.8** — Failure Memory Agent, persistent SQLite incident store, and memory-aware repair planning. *(implemented)* Next: real GitHub Actions adapter, automatic repair PR creation, and cross-provider calibration.

**v1.0** — reproducible CI-failure benchmark suite, learned ranking calibration, dashboard, production policy controls, and independently reproducible production evidence.

## Design principle

> Fix the earliest causal failure, learn from prior evidence, isolate every mutation, verify targeted behavior and full regression, compare alternatives independently, and rollback when production evidence is insufficient.

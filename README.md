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
 Repair Planner Agent
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

A CI run may show `Type Check ❌ → Unit Test ❌ → Integration Test ❌ → Deploy ❌`. The visible deploy failure can be downstream noise. The orchestrator ranks the earliest causal failure, constrains the repair scope, lets multiple agents propose bounded candidates, evaluates them independently, chooses the best admissible candidate, and stops unsafe or unproductive repair loops.

## Features

- Pipeline dependency DAG with cycle validation
- Error classification and confidence
- Root-cause ranking based on upstream impact, causal rules, depth, severity, and criticality
- Causal failure graph with evidence and edge confidence
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
- Selective verification planner: root stage → predicted downstream failures → full pipeline
- Retry/escalation primitives and hash-chained audit log
- Benchmark metrics for Top-1/Top-3 RCA accuracy and cascade elimination

## v0.7 execution layer

### GitHub Actions collector

`GitHubActionsCollector` accepts injected GitHub API functions for jobs and logs and returns only failed, cancelled, or timed-out jobs as normalized snapshots. Authentication and SDK details stay outside the orchestration core.

### Isolated repair workspace

`IsolatedGitWorkspace` creates one temporary Git worktree and branch per candidate. Agent patches are applied inside that worktree, not directly to the source checkout. Failed evaluation can call `rollback()` and cleanup removes the worktree.

### Targeted test runner

`TargetedTestRunner` executes affected tests first and can then run the full pytest suite. It captures return code, pass/fail, latency, stdout, stderr, and returns timeout as a failed result rather than hanging the repair loop.

### Canary boundary

`CanaryController` separates deployment, health checking, and rollback into injected hooks. A healthy canary may proceed; an unhealthy canary immediately invokes rollback and records whether rollback itself succeeded.

## Real coding-agent adapter contract

`CommandCodingAgent` serializes the approved `RepairPlan` to JSON and sends it to the configured command on **stdin**. The command must emit one JSON object on stdout:

```json
{
  "summary": "fix Optional handling",
  "changed_files": ["src/foo.py"],
  "patch": "diff --git ...",
  "confidence": 0.91
}
```

The adapter invokes an explicit argv sequence with `shell=False`; prompts are not embedded into command-line arguments. This keeps the core compatible with wrapper scripts for Cursor, Codex, Claude, Orca, or other coding-agent CLIs without hard-coding vendor-specific flags.

## Safety properties

```text
Agent proposes patch
      ↓
approved file scope?
      ↓
human approval required?
      ↓
apply only in isolated worktree
      ↓
targeted tests
      ↓
full regression
      ↓
tournament + policy
      ↓
canary
      ↓
healthy? ── no ──> rollback
      ↓ yes
signed evidence
```

The coding agent never gets authority to select arbitrary files, declare itself successful, bypass regression checks, release itself, or retry indefinitely.

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

- Top-1 / Top-3 Root Cause Accuracy
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
- Targeted-test precision / recall
- Invalid-agent-output rate
- Evidence signature verification rate
- Canary success rate
- Rollback success rate

## Roadmap

**v0.4** — bounded repair planner/executor/evaluator loop with retry and escalation. *(implemented)*

**v0.5** — multi-agent candidate tournament, utility scoring, policy gate, and production evidence. *(implemented)*

**v0.6** — CLI coding-agent adapter, runtime telemetry, affected-test hooks, and signed evidence envelopes. *(implemented)*

**v0.7** — GitHub Actions failed-job/log collector, isolated git worktree patch application, executable targeted/full test runner, canary boundary, and rollback hooks. *(core execution contracts implemented)*

**v0.8** — wire the collector directly to GitHub REST/Actions adapters, persist per-candidate telemetry, execute real canary providers, secret-manager signing, and create repair PRs automatically.

**v1.0** — reproducible CI-failure benchmark suite, learned ranking calibration, dashboard, production policy controls, cross-provider agent benchmarking, and independently reproducible production evidence.

## Design principle

> Fix the earliest causal failure, isolate every mutation, verify targeted behavior and full regression, compare alternatives with independent evidence, and rollback when production evidence is insufficient.

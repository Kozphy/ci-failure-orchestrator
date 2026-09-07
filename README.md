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
 CLI / provider adapters
          ↓
 Bounded Agent Executor
          ↓
 Affected-test selection
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
 Signed Production Evidence
```

A CI run may show `Type Check ❌ → Unit Test ❌ → Integration Test ❌ → Deploy ❌`. The visible deploy failure can be downstream noise. The orchestrator ranks the earliest causal failure, constrains the repair scope, lets multiple agents propose bounded candidates, evaluates them independently, chooses the best admissible candidate, and stops unsafe or unproductive repair loops.

## Features

- Pipeline dependency DAG with cycle validation
- Error classification and confidence
- Root-cause ranking based on upstream impact, causal rules, depth, severity, and criticality
- Causal failure graph with evidence and edge confidence
- GitHub Actions job/log ingestion from normalized API payloads
- Repair Planner Agent with bounded hypotheses, risk classification, rollback intent, and human-approval gating
- Provider-neutral Coding Agent protocol
- CLI coding-agent adapter using JSON over stdin/stdout with no shell invocation
- Coding Agent Executor that rejects out-of-scope or empty patches
- Conservative affected-test selection with explicit mapping hooks and full-suite fallback
- Independent evaluation contract for targeted checks and full regression
- Retry budget and explicit stopping conditions
- Immediate rollback/escalation path when regression is detected
- Multi-agent Repair Tournament with utility-based candidate selection
- Cost, latency, confidence, evaluation, and risk-aware candidate scoring
- Final Policy Gate with automated thresholds and human-approval fallback
- Hashable Production Evidence record for the selected candidate and release decision
- HMAC-SHA256 signed evidence envelopes with tamper verification
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

## Real coding-agent adapter contract

`CommandCodingAgent` is the first runnable provider adapter. The orchestrator serializes the approved `RepairPlan` to JSON and sends it to the configured command on **stdin**. The command must emit one JSON object on stdout:

```json
{
  "summary": "fix Optional handling",
  "changed_files": ["src/foo.py"],
  "patch": "diff --git ...",
  "confidence": 0.91
}
```

The adapter invokes an explicit argv sequence with `shell=False`; prompts are not embedded into command-line arguments. This keeps the core compatible with wrapper scripts for Cursor, Codex, Claude, Orca, or other coding-agent CLIs without hard-coding vendor-specific flags.

The adapter captures process latency, return code, stdout size, and stderr size. A non-zero exit or malformed JSON fails closed before evaluation.

## Coding Agent Executor

`CodingAgentExecutor` is the policy boundary between planning and code mutation. An agent receives a `RepairPlan` and returns a `PatchProposal`. The executor rejects a proposal when it edits files outside the approved target scope, returns an empty patch, or attempts to execute a high-risk plan without approval.

## Affected-test selection

`select_affected_tests()` supports an explicit source-to-test map as the preferred production mechanism. It also has a small Python convention fallback such as:

```text
src/pkg/foo.py → tests/pkg/test_foo.py
```

When no trustworthy mapping exists it does **not** guess: it returns `fallback_to_full_suite=True`.

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

## Policy Gate and signed Production Evidence

`RepairPolicyGate` is a separate decision boundary after candidate selection. It can return:

```text
READY_FOR_CANARY
HUMAN_APPROVAL_REQUIRED
BLOCK
ESCALATE_HUMAN
```

The gate checks risk, cost, latency, and independent evaluation rather than trusting the winning agent. `build_production_evidence()` records the root stage, selected agent, evaluation score, risk, cost, latency, candidate count, policy action, and a deterministic SHA-256 evidence hash.

`sign_evidence()` wraps that record in an HMAC-SHA256 envelope. `verify_evidence()` detects payload tampering. Production deployments should obtain the signing key from a secret manager and rotate it by `key_id`; the key is never stored in the evidence payload.

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
- Targeted-test precision / recall
- Invalid-agent-output rate
- Evidence signature verification rate

## Roadmap

**v0.3** — direct GitHub API collector for workflow runs/jobs/logs and workflow-DAG reconstruction.

**v0.4** — bounded repair planner/executor/evaluator loop with retry and escalation. *(core contracts implemented)*

**v0.5** — multi-agent candidate tournament, utility scoring, policy gate, and production evidence. *(core contracts implemented)*

**v0.6** — CLI coding-agent adapter, runtime telemetry, affected-test hooks, and signed evidence envelopes. *(core contracts implemented)*

**v0.7** — GitHub Actions run collector, isolated worktree/container patch application, targeted test runner, canary integration, and executable rollback.

**v1.0** — reproducible CI-failure benchmark suite, learned ranking calibration, dashboard, production policy controls, cross-provider agent benchmarking, and independently reproducible production evidence.

## Design principle

> Fix the earliest causal failure, constrain every repair, compare alternatives with independent evidence, and escalate when policy confidence is insufficient.

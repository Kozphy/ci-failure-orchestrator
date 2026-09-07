# CI Failure Orchestrator

Dependency-aware **CI/CD/CT failure control plane** for causal diagnosis, bounded multi-agent repair, persistent failure memory, independent evaluation, policy gating, rollback, telemetry, and production evidence.

## Architecture

```text
GitHub Actions failures
        ↓
Failure Dependency Graph
        ↓
Root-cause classification / ranking
        ↓
Failure Memory Agent + SQLiteIncidentStore
        ↓
Memory-Aware Repair Planner
        ↓
Multiple Coding Agents
        ├─ general repair agents
        └─ MergeConflictRepairAgent
        ↓
Bounded Agent Executor
        ↓
Isolated Git Worktree / Sandbox
        ↓
Affected-test selection
        ↓
Targeted tests + full regression
        ↓
Independent Evaluator
        ↓
Candidate Tournament
        ↓
Retry / stopping conditions
        ↓
Policy Gate / Human Approval
        ↓
Canary / Rollback
        ↓
Signed + hash-chained Production Evidence
```

The core rule is separation of duties: **agents may propose repairs, but they cannot approve their own release.** Regression checks, policy gates, budgets, and human escalation remain authoritative.

## What is implemented

- pipeline DAG validation, causal edge inference, and root-cause ranking
- failure classification and confidence scoring
- replayable root-cause and cascade-elimination benchmarks
- deterministic and provider-neutral repair interfaces
- persistent `FailureMemoryAgent` backed by SQLite
- bounded memory-aware repair planning that never promotes regression-producing history
- multiple coding-agent execution and candidate tournament scoring
- `MergeConflictRepairAgent` for bounded, proposal-only Git conflict resolution
- isolated workspaces/worktrees for mutations
- conservative affected-test selection and full-regression fallback
- retry, cost, latency, and risk budgets
- fail-closed release policy and human-approval boundary
- canary health/rollback boundary
- signed/hash-chained production evidence
- executable repair fixtures and ablation benchmarks
- Production Proof GitHub Actions gate with machine-readable artifacts

## MergeConflictRepairAgent

`MergeConflictRepairAgent` reads only files approved by the repair plan, parses Git conflict blocks, and emits a unified-diff proposal. The default `ConservativeMergeResolver` resolves only deterministic cases such as identical sides, one-sided additions, or strict superset edits.

Semantic conflicts fail closed:

```text
conflicted PR
   ↓
approved conflicted files
   ↓
MergeConflictRepairAgent
   ↓
unambiguous? ── yes ──> patch proposal
      │                     ↓
      no                sandbox + tests
      ↓                     ↓
human / stronger agent   evaluator + policy
```

It never edits the live repository, merges a PR, or self-approves a resolution. Ambiguous blocks return an empty proposal so the existing executor rejects the attempt and the orchestrator can escalate.

## Failure Memory

Historical incidents are advisory evidence, not execution authority. Similar incidents can contribute repair context and affected-test hints, while past regression-producing fixes remain visible only as warnings.

```text
new incident
   ↓
MemoryQuery
   ↓
SQLiteIncidentStore
   ↓
retrieve top-K similar incidents
   ↓
separate successful history from regression history
   ↓
MemoryAwareRepairPlanner
```

## Production Proof

The repository carries reproducible evidence artifacts for different layers of the system:

- `corpus-benchmark.json` — causal RCA and cascade elimination
- `repair-fixture-benchmark.json` — executable deterministic repairs
- `repair-ablation.json` — system-component ablation comparison
- `agent-eval-benchmark.json` — provider-neutral agent telemetry contract
- `production-gate.json` — explicit PASS/BLOCK policy decision

Claims are scoped to the evidence source. Synthetic/replay benchmarks are not presented as production incident or live-model performance.

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

## Safety invariants

1. Agents cannot self-approve release.
2. Unknown failures fail closed or escalate.
3. Regression blocks automated release.
4. Retry, cost, latency, risk, file-scope, and diff-size budgets bound autonomy.
5. Mutations execute in isolated workspaces.
6. Targeted tests alone cannot replace full regression verification.
7. Historical memory cannot bypass evaluation or policy.
8. Merge-conflict resolution is proposal-only; ambiguous conflicts escalate.
9. Material decisions produce auditable evidence.

## Evaluation targets

- Top-1 / Top-3 root-cause accuracy
- false-root-cause rate
- cascade elimination
- repair success / first-attempt success
- merge-conflict auto-resolution rate
- semantic-conflict escalation precision
- regression and regression-escape rate
- human escalation rate
- mean attempts / MTTR
- P50 / P95 latency
- cost per resolved incident
- memory precision@K and repair-success lift
- candidate win rate by agent/provider
- targeted-test precision / recall
- canary and rollback success
- evidence signature verification

## Version direction

**v0.8** integrates persistent learning/memory with the previously merged autonomous repair and Production Proof control-plane layers, including bounded merge-conflict repair. The next evidence milestone is real provider-backed semantic conflict resolution, automatic repair PR creation, cross-provider calibration, and externally reproducible held-out evaluation.

## Design principle

> Find the earliest causal failure, learn from bounded historical evidence, propose the smallest repair, isolate every mutation, verify independently, and stop before autonomy becomes unsafe.

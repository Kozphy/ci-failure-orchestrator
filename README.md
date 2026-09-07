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
             ├─ ConservativeMergeResolver
             └─ SemanticMergeResolver
                    ↓
             OpenAI semantic provider
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
- deterministic-first + model-backed semantic merge resolution chain
- OpenAI semantic merge provider with structured JSON-only output
- confidence, output-size, empty-output, and conflict-marker rejection before patch admission
- held-out synthetic merge-conflict corpus and reproducible benchmark
- isolated workspaces/worktrees for mutations
- conservative affected-test selection and full-regression fallback
- retry, cost, latency, and risk budgets
- fail-closed release policy and human-approval boundary
- canary health/rollback boundary
- signed/hash-chained production evidence
- executable repair fixtures and ablation benchmarks
- Production Proof GitHub Actions gate with machine-readable artifacts

## MergeConflictRepairAgent

`MergeConflictRepairAgent` reads only files approved by the repair plan, parses Git conflict blocks, and emits a unified-diff proposal. The default `ConservativeMergeResolver` resolves deterministic cases such as identical sides, one-sided additions, or strict superset edits.

For semantic conflicts, the agent can use a `ChainedMergeResolver`:

```python
from ci_failure_orchestrator.merge_conflict_agent import (
    ChainedMergeResolver,
    ConservativeMergeResolver,
    MergeConflictRepairAgent,
    SemanticMergeResolver,
)
from ci_failure_orchestrator.openai_merge_resolver import OpenAISemanticMergeProvider

resolver = ChainedMergeResolver(
    ConservativeMergeResolver(),
    SemanticMergeResolver(
        OpenAISemanticMergeProvider(model="gpt-5.6"),
        min_confidence=0.80,
    ),
)
agent = MergeConflictRepairAgent(resolver=resolver)
```

The semantic provider returns only a proposed resolved text block plus confidence and rationale. It has no filesystem, shell, git, merge, or approval authority.

```text
conflicted PR
   ↓
approved conflicted files
   ↓
Conservative resolver
   ├─ resolved → patch candidate
   └─ ambiguous
          ↓
   Semantic resolver
          ↓
   confidence >= threshold?
      ├─ no → escalate
      └─ yes
          ↓
   marker/size validation
          ↓
      patch proposal
          ↓
   sandbox + tests
          ↓
 evaluator + policy
          ↓
 release / retry / block / human
```

The semantic path fails closed when confidence is below threshold, output is empty or oversized, or conflict markers remain. Even an accepted semantic resolution is only a patch candidate; it still requires independent verification.

Install the optional provider integration with:

```bash
python -m pip install -e ".[dev,openai]"
```

## Merge-conflict benchmark

`benchmark/merge_conflict_corpus.v1.json` is a held-out synthetic corpus that separates deterministic conflicts from semantic conflicts. The default Production Proof run uses only the deterministic resolver so semantic cases must escalate rather than guess.

```bash
python scripts/run_merge_conflict_benchmark.py
```

The generated `artifacts/merge-conflict-benchmark.json` records:

- auto-resolution rate
- exact-match rate for deterministic cases
- escalation rate
- semantic-conflict escalation precision
- unsafe-output rate

The v1 corpus is deliberately small and synthetic. It is evidence that the resolver behaves correctly under controlled cases, **not** evidence of production-scale semantic merge performance. Live-provider evaluation should use a separate held-out corpus, repeated runs, token/latency/cost telemetry, and regression verification.

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
- `merge-conflict-benchmark.json` — held-out deterministic/fail-closed conflict evidence
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
8. Merge-conflict resolution is proposal-only; unresolved/low-confidence semantic conflicts escalate.
9. Model output cannot directly invoke filesystem, shell, git, merge, or release operations.
10. Material decisions produce auditable evidence.

## Evaluation targets

- Top-1 / Top-3 root-cause accuracy
- false-root-cause rate
- cascade elimination
- repair success / first-attempt success
- merge-conflict auto-resolution rate
- semantic-conflict resolution success
- semantic-conflict escalation precision
- unsafe semantic-resolution rejection rate
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

**v0.8.2** adds a held-out merge-conflict benchmark and Production Proof artifact on top of deterministic-first, provider-backed semantic resolution. The next evidence milestone is live semantic-provider evaluation with repeated held-out runs, real token/latency/cost telemetry, and automatic repair-PR creation behind the existing policy boundary.

## Design principle

> Find the earliest causal failure, learn from bounded historical evidence, propose the smallest repair, isolate every mutation, verify independently, and stop before autonomy becomes unsafe.

# CI Failure Orchestrator

**v1.1 agentic CI reliability control plane** for dependency-aware diagnosis, bounded autonomous repair, multi-provider worker routing, candidate tournaments, persistent failure memory, independent evaluation, fleet policy, SLO/error-budget control, canary rollout, benchmarking, dashboard telemetry, human escalation, and tamper-evident production proof.

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
Retry / cost / latency budgets
        ↓
GREEN / REVIEW / ESCALATE / DENY
        ↓
Canary Rollout / Rollback
        ↓
Fleet Manager
        ↓
SLO + error-budget gate
        ↓
Dashboard + production proof
```

The primary safety rule is separation of duties: **repair workers may propose changes, but they cannot approve their own release.** Evaluation, regression checks, repository policy, canary health, fleet policy, SLOs, and human approval retain release authority.

## v1.1 control-plane capabilities

### Policy-driven agent supervisor

`SupervisorPolicy` classifies candidate repairs as low, medium, high, or critical risk and grants only the maximum safe authority:

- low risk → autonomous patch with required verification
- medium risk → patch allowed, human review required
- high risk → RCA only
- critical risk → mutation denied

Autonomy is bounded by retry count, changed files, changed lines, cost, and elapsed time. Test weakening, regressions, security findings, protected paths, and critical surfaces fail closed.

### GitHub Actions repair adapter

`FailedCheck -> SupervisorDecision -> AgentTask` converts GitHub Actions evidence into a provider-neutral worker contract containing:

- objective
- failure class
- authority
- allowed paths
- required gates
- forbidden actions
- evidence

Workers never receive merge, approval, or release authority.

### Bounded autonomous repair state machine

`RepairIncident` and `RepairCoordinator` implement an auditable lifecycle:

```text
DETECTED
  ↓
PLANNED
  ↓
DISPATCHED
  ↓
VERIFYING
  ├─ GREEN
  ├─ REVIEW_REQUIRED
  ├─ RERUNNING → DETECTED
  ├─ DENIED
  └─ ESCALATED
```

Every transition receives a SHA-256 digest so repair lifecycle evidence can be validated independently.

### Multi-provider agent routing

`route_workers()` filters coding agents by authority, failure-class capability, and remaining incident cost budget. The control plane is provider-neutral; Copilot, OpenAI, or custom workers can implement the same contract.

### Candidate tournament

`select_candidate()` applies hard safety gates before ranking candidates. Unsafe patches can never win regardless of confidence, speed, or price.

Among safe candidates, the deterministic baseline prefers:

1. lower cost
2. lower latency
3. smaller patch
4. higher confidence
5. stable worker-name tie break

### Repair effectiveness telemetry

`RepairObservation` and `RepairMetrics` measure whether autonomous repair actually works:

- repair success rate
- false-repair rate
- mean repair cost
- cost per successful repair
- mean latency
- P95 repair latency
- mean attempts
- provider-level comparisons

A patch proposal is not counted as success. Success is recorded only after independent verification.

### Multi-repository fleet management

`FleetManager` registers repository-specific policies and evaluates repository snapshots across a fleet. It can permit repair, queue work, deny automation, or freeze a repository when SLO error-budget burn or canary health makes autonomy unsafe.

Repository policy includes:

- automation enabled/disabled
- autonomy level
- repair concurrency budget
- human-approval threshold
- canary group

### Benchmark suite

`BenchmarkSuite` aggregates replayable repair cases into production-facing metrics:

- Top-1 root-cause accuracy
- Top-3 root-cause accuracy
- repair success rate
- false-repair rate
- regression rate
- escalation rate
- mean retries
- mean cost
- P50/P95 repair latency

### SLO and error budgets

`evaluate_slo()` checks observed reliability against explicit targets for:

- workflow availability
- repair success rate
- false-repair rate
- P95 repair latency

It also calculates availability error-budget burn. Excess burn can freeze autonomous repair at fleet level.

### Canary controller

`evaluate_canary()` returns one of:

- `promote`
- `hold`
- `rollback`

Promotion requires sufficient sample size, acceptable repair success, bounded regression/false-repair rates, and acceptable latency. Regression or false-repair threshold breaches trigger rollback. `CanaryController` provides the execution boundary for canary deployment, health check, and rollback hooks.

### Fleet dashboard model

`build_dashboard_snapshot()` combines fleet decisions, SLO state, and benchmark evidence into a machine-readable snapshot with fleet health, repair/freeze/queue counts, error-budget burn, RCA accuracy, repair quality, and P95 latency.

The snapshot is deliberately UI-independent so it can feed a terminal report, JSON artifact, Grafana/Prometheus exporter, or web dashboard without coupling control logic to presentation code.

### Production proof

Production readiness is represented by evidence rather than a claim. `build_production_proof()` binds together:

- repository + run ID
- commit SHA
- gate decision
- evaluator score
- regression status
- canary decision
- SLO result
- evidence artifacts and digests
- UTC creation timestamp
- SHA-256 proof hash

The existing hash-chained audit/evidence sink remains the event-level tamper-evident history; the production proof bundle is the release-level summary artifact.

## Platform façade

`CIRepairPlatform` combines fleet policy, benchmark evidence, SLO evaluation, canary evaluation, and dashboard generation into one fleet-level control path.

```python
from ci_failure_orchestrator.benchmark_suite import BenchmarkResult
from ci_failure_orchestrator.canary import CanaryMetrics
from ci_failure_orchestrator.fleet import FleetManager, RepositoryPolicy, RepositorySnapshot
from ci_failure_orchestrator.platform import CIRepairPlatform
from ci_failure_orchestrator.slo import SLOObservation

fleet = FleetManager()
fleet.register(RepositoryPolicy("Kozphy/Windows-Network-Recovery-Toolkit"))

platform = CIRepairPlatform(fleet)
report = platform.evaluate(
    repositories=[
        RepositorySnapshot(
            "Kozphy/Windows-Network-Recovery-Toolkit",
            open_failures=1,
        )
    ],
    benchmark_results=[
        BenchmarkResult(
            case_id="proxy-drift-001",
            root_stage_correct=True,
            repaired=True,
            regression=False,
            escalated=False,
            retries=1,
            cost=0.05,
            latency_ms=1200,
            root_cause_top3=True,
            false_repair=False,
        )
    ],
    slo_observation=SLOObservation(
        total_runs=100,
        successful_runs=100,
        successful_repairs=95,
        attempted_repairs=100,
        false_repairs=1,
        p95_repair_latency_ms=10_000,
    ),
    canary_metrics=CanaryMetrics(
        sample_size=20,
        success_rate=0.95,
        regression_rate=0.0,
        false_repair_rate=0.0,
        p95_latency_ms=10_000,
    ),
)

print(report.dashboard.to_dict())
```

## Persistent Failure Memory

Historical incidents are advisory evidence, not execution authority. Similar incidents can contribute repair context and affected-test hints, while past regression-producing fixes remain visible only as warnings and are never promoted.

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

## Held-out merge-conflict benchmarks

`benchmark/merge_conflict_corpus.v1.json` is a held-out synthetic corpus that separates deterministic conflicts from semantic conflicts. The default Production Proof run uses only the deterministic resolver so semantic cases must escalate rather than guess.

```bash
python scripts/run_merge_conflict_benchmark.py
```

## Quick start

```bash
python -m pip install -e ".[dev]"
pytest
```

Analyze normalized GitHub Actions evidence:

```bash
ci-orchestrator analyze \
  --jobs examples/github_jobs.json \
  --logs examples/github_logs.json \
  --audit audit.jsonl
```

## Production operating model

A production deployment should treat the project as a control plane, not as permission for unconstrained agents:

```text
failure detected
   ↓
causal RCA
   ↓
supervisor policy
   ↓
provider routing
   ↓
candidate repair proposals
   ↓
independent gates
   ↓
candidate tournament
   ↓
full regression verification
   ↓
repository policy gate
   ↓
canary
   ↓
SLO/error-budget check
   ↓
PR / human approval when required
   ↓
release
   ↓
production proof
```

A bad canary, detected regression, unknown failure, exhausted autonomy budget, no safe candidate, or excessive error-budget burn must stop or freeze autonomous repair rather than silently widening autonomy.

## Safety invariants

1. Repair agents cannot self-approve release.
2. Regression detection blocks release.
3. Unknown failures fail closed and escalate.
4. Retry, cost, latency, concurrency, and error-budget limits bound autonomy.
5. Mutations execute in isolated workspaces/worktrees.
6. Targeted tests alone cannot replace full regression verification.
7. Historical memory cannot bypass evaluation or policy.
8. Merge-conflict resolution is proposal-only; unresolved/low-confidence semantic conflicts escalate.
9. Model output cannot directly invoke filesystem, shell, git, merge, or release operations.
10. Canary regression or false-repair breaches trigger rollback.
11. Repository policy remains authoritative inside fleet orchestration.
12. Every material decision should produce machine-readable, auditable evidence.
13. Unsafe candidate patches can never win a provider tournament.
14. Repair effectiveness is measured from verified outcomes, not agent self-report.

## Version status

**v1.1 control-plane layer** integrates policy-driven supervision, GitHub Actions evidence normalization, bounded repair lifecycle state, multi-provider worker routing, safe candidate tournaments, repair-effectiveness telemetry, fleet management, persistent failure memory, merge-conflict resolution, benchmark metrics, SLO/error-budget evaluation, canary promotion/rollback policy, dashboard aggregation, and release-level production proof.

## Design principle

> Find the earliest causal failure, route only to eligible bounded workers, reject unsafe candidates before ranking, verify independently, widen rollout gradually, and freeze autonomy when evidence says the system is unsafe.

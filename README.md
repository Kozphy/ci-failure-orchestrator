# CI Failure Orchestrator

**v1.0 multi-repository CI repair platform** for dependency-aware diagnosis, bounded autonomous repair, independent evaluation, fleet policy, SLO/error-budget control, canary rollout, benchmarking, dashboard telemetry, human escalation, and tamper-evident production proof.

```text
GitHub repositories
        ↓
Workflow runs / jobs / logs
        ↓
Failure Dependency Graph
        ↓
Root-cause classification + ranking
        ↓
Repair planner
        ↓
Coding agents / patch executors
        ↓
Independent evaluator
        ↓
Retry / cost / latency budgets
        ↓
Regression detection
        ↓
Repository policy gate
        ↓
Canary rollout
        ↓
Fleet manager
        ↓
SLO + error-budget gate
        ↓
Dashboard + production proof
```

The primary safety rule is separation of duties: **repair agents may propose changes, but they cannot approve their own release.** Evaluation, regression checks, repository policy, canary health, fleet policy, SLOs, and human approval retain release authority.

## v1 platform capabilities

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

Promotion requires sufficient sample size, acceptable repair success, bounded regression/false-repair rates, and acceptable latency. Regression or false-repair threshold breaches trigger rollback.

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

## Existing single-run repair control plane

The v1 platform builds on the existing causal and repair primitives:

- `PipelineGraph` for workflow DAG reasoning
- typed CI failure classification
- causal-edge inference
- root-cause ranking
- selective verification planning
- deterministic, test, security, and general coding-agent strategies
- `RegressionAwareEvaluator`
- bounded retry/cost/latency autonomy
- fail-closed `DefaultRepairPolicy`
- first-class human escalation
- hash-chained JSONL evidence

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

A production deployment should treat v1 as a control plane, not as permission for unconstrained agents:

```text
failure detected
   ↓
causal RCA
   ↓
smallest repair proposal
   ↓
isolated patch/worktree
   ↓
targeted verification
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

A bad canary, detected regression, unknown failure, exhausted autonomy budget, or excessive error-budget burn must stop or freeze autonomous repair rather than silently widening autonomy.

## v1 production-proof checklist

A deployment is not considered proven merely because the code exists. Production proof should include real evidence for:

- multiple repositories under distinct fleet policies
- replayable failure corpus and benchmark results
- before/after RCA and MTTR metrics
- false-repair and regression measurements
- SLO/error-budget history
- canary promotion and rollback exercises
- failure injection
- rollback/recovery evidence
- audit-chain verification
- cost and latency telemetry
- security-policy enforcement
- real GitHub Actions runs and PRs
- reproducible deployment instructions
- dashboard screenshots or exported snapshots

## Safety invariants

1. Repair agents cannot self-approve release.
2. Regression detection blocks release.
3. Unknown failures fail closed and escalate.
4. Retry, cost, latency, concurrency, and error-budget limits bound autonomy.
5. Canary regression or false-repair breaches trigger rollback.
6. Repository policy remains authoritative inside fleet orchestration.
7. Every material decision should produce machine-readable evidence.
8. Full regression verification remains the final technical authority before production release.

## Version status

**v1.0.0 platform layer** adds multi-repository fleet management, expanded benchmark metrics, SLO/error-budget evaluation, canary promotion/rollback policy, dashboard aggregation, release-level production proof, and an integrated platform façade.

The next production-hardening work is operational rather than architectural: real GitHub run/patch execution adapters, persistent run state, OpenTelemetry exporters, a hosted dashboard, controlled canary deployments, multi-repository soak tests, and externally reproducible benchmark evidence.

## Design principle

> Find the earliest causal failure, propose the smallest repair, verify independently, widen rollout gradually, and freeze autonomy when evidence says the system is unsafe.

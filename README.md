# CI Failure Orchestrator

Dependency-aware **CI/CD/CT failure control plane** for causal diagnosis, bounded autonomous repair, regression-aware evaluation, policy gating, escalation, telemetry, and tamper-evident production evidence.

## v0.3: autonomous repair control plane

```text
Failure Dependency Graph
        ↓
Root-cause classification
        ↓
Repair planner
        ↓
Multiple coding agents
        ↓
Evaluator
        ↓
Retry budget
        ↓
Stopping condition
        ↓
Regression detection
        ↓
Policy gate
        ↓
Human escalation
        ↓
Cost / latency telemetry
        ↓
Production evidence
```

The core design rule is separation of duties: **coding agents may propose repairs, but they do not decide whether their own patch is safe to release.** Release authority belongs to the evaluator + policy gate.

## Architecture

### 1. Failure Dependency Graph
`PipelineGraph` validates the pipeline DAG, calculates depth and descendants, and supports upstream/downstream causal reasoning.

### 2. Root-cause classification
The classifier maps logs into typed failures such as dependency, build, test, flaky, security, runtime, network, and deployment failures with confidence scores.

### 3. Repair planner
`RepairControlPlane._plan()` gathers proposals from specialized agents and ranks them by confidence and expected cost.

### 4. Multiple coding agents
Included strategies:

- `DeterministicRepairAgent` — types, dependencies, builds, packages, infrastructure retry
- `TestRepairAgent` — assertion/runtime repair and flaky-test quarantine/retry
- `SecurityRepairAgent` — safe dependency upgrade path
- `GeneralCodingAgent` — lower-confidence agentic patching for known non-deterministic failures

Unknown failures fail closed and escalate rather than being blindly patched.

### 5. Evaluator + regression detection
`RegressionAwareEvaluator` consumes CI verification signals and produces an independent evaluation containing pass/fail, regression status, score, and reasons.

### 6. Retry budget + stopping conditions
Autonomy is bounded by three independent budgets:

- maximum retries
- maximum repair cost
- maximum latency

Exhausting any budget escalates to a human.

### 7. Policy gate
`DefaultRepairPolicy` is fail-closed:

- verified + high score + regression-free → `release`
- potentially recoverable → `retry`
- regression detected → `block`
- low confidence / unknown / exhausted budget → `escalate`

### 8. Human escalation
Escalation is a first-class terminal decision, not an exception path. Every escalation records a machine-readable reason and history.

### 9. Cost / latency telemetry
Each evaluated proposal records estimated cost, observed evaluation latency, strategy, score, pass status, regression status, and orchestration history. The control plane accumulates cost and latency for stopping decisions.

### 10. Production evidence
`HashChainedEvidenceSink` writes append-only JSONL records linked by SHA-256 hashes. This provides tamper-evident evidence for classification, evaluation, policy decisions, and escalation events.

## Existing causal intelligence

The project also includes:

- causal edge inference
- root-cause ranking based on upstream impact, causal rules, depth, severity, and criticality
- GitHub Actions job/log ingestion from normalized API payloads
- selective verification planning
- full-pipeline regression verification
- benchmark metrics for Top-1/Top-3 RCA accuracy and cascade elimination

## Quick start

```bash
python -m pip install -e ".[dev]"
pytest
```

Existing CLI example:

```bash
ci-orchestrator analyze \
  --jobs examples/github_jobs.json \
  --logs examples/github_logs.json \
  --audit audit.jsonl
```

## Control-plane example

```python
from ci_failure_orchestrator.control_plane import RepairControlPlane
from ci_failure_orchestrator.policy import DefaultRepairPolicy
from ci_failure_orchestrator.production import HashChainedEvidenceSink, RegressionAwareEvaluator
from ci_failure_orchestrator.repair_agents import (
    DeterministicRepairAgent,
    GeneralCodingAgent,
    SecurityRepairAgent,
    TestRepairAgent,
)

control = RepairControlPlane(
    graph,
    [
        DeterministicRepairAgent(),
        TestRepairAgent(),
        SecurityRepairAgent(),
        GeneralCodingAgent(),
    ],
    RegressionAwareEvaluator(tests_passed=True, regression_free=True, score=0.97),
    DefaultRepairPolicy(),
    HashChainedEvidenceSink("production-evidence.jsonl"),
    max_retries=2,
    max_cost=1.0,
    max_latency_ms=30_000,
)

decision = control.run(failure)
```

## Evaluation targets

- Top-1 Root Cause Accuracy
- Top-3 Root Cause Accuracy
- False Root-Cause Rate
- Cascading Failures Eliminated
- Auto-repair success rate
- False-repair rate
- Regression rate
- Human escalation rate
- Mean retries before resolution
- MTTR reduction
- Cost per successful repair
- P50/P95 repair latency

## Safety invariants

1. Agents cannot self-approve a release.
2. A detected regression blocks release.
3. Unknown failures escalate.
4. Cost, retry, and latency budgets bound autonomy.
5. Every material decision produces evidence.
6. Full regression verification remains the final authority before production release.

## Next milestones

**v0.4** — wire the repair proposals to real patch executors/worktrees, affected-test selection, rollback, and GitHub PR approval gates.

**v0.5** — OpenTelemetry metrics/traces, persistent run state, calibrated policy thresholds, replayable failure corpus, and provider adapters for multiple coding agents.

**v1.0** — reproducible CI-failure benchmark suite, canary deployment, SLOs, production dashboard, multi-repository fleet management, and externally reproducible evaluation evidence.

## Design principle

> Find the earliest causal failure, propose the smallest repair, verify independently, and stop before autonomy becomes unsafe.

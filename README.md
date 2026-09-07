# CI Failure Orchestrator

Dependency-aware **causal CI/CD/CT failure orchestration**. Instead of fixing the latest red job, it asks which failure most plausibly caused the others and verifies that hypothesis with the smallest useful rerun plan.

## v0.2: causal failure intelligence

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
Selective verification plan
          ↓
 Full-pipeline regression check
          ↓
 Benchmark + audit evidence
```

A CI run may show `Type Check ❌ → Unit Test ❌ → Integration Test ❌ → Deploy ❌`. The visible deploy failure can be downstream noise. The orchestrator ranks the earliest causal failure, records evidence for failure-to-failure edges, and proposes a verification sequence that tests the root-cause hypothesis before rerunning the entire pipeline.

## Features

- Pipeline dependency DAG with cycle validation
- Error classification and confidence
- Root-cause ranking based on upstream impact, causal rules, depth, severity, and criticality
- Causal failure graph with evidence and edge confidence
- GitHub Actions job/log ingestion from normalized API payloads
- Selective verification planner: root stage → predicted downstream failures → full pipeline
- Retry/escalation primitives and hash-chained audit log
- Benchmark metrics for Top-1/Top-3 RCA accuracy and cascade elimination

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

The output includes the predicted root cause, ranked hypotheses, causal edges, and the minimal verification plan.

## Evaluation targets

- Top-1 Root Cause Accuracy
- Top-3 Root Cause Accuracy
- False Root-Cause Rate
- Cascading Failures Eliminated
- Mean retries before resolution
- MTTR reduction
- Verification cost
- Auto-fix success rate

A causal prediction is stronger when fixing the predicted root cause actually removes the downstream failures it claimed to explain.

## Roadmap

**v0.3** — direct GitHub API collector for workflow runs/jobs/logs and workflow-DAG reconstruction.

**v0.4** — patch planner, affected-test selection, risk scoring, rollback, and human approval gates.

**v1.0** — reproducible CI-failure benchmark suite, learned ranking calibration, dashboard, and production-grade policy controls.

## Design principle

> Fix the earliest causal failure, not the latest visible failure.

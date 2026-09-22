# Governed pipeline runbook

## Local happy path

```bash
python -m pip install -e ".[dev]"
ci-orchestrator run --fixture benchmarks/cases/01_unit_test_failure.json --audit artifacts/governed-audit.jsonl
ci-orchestrator explain <run_id>
ci-orchestrator replay <run_id>
ci-orchestrator benchmark --cases benchmarks/cases
```

## Diagnosis-only (existing)

```bash
ci-orchestrator analyze --jobs examples/github_jobs.json --logs examples/github_logs.json --audit audit.jsonl
```

## Trust control plane (existing)

```bash
ci-orchestrator trust-run --scenario examples/trust-scenario.yaml --audit evidence/audit.jsonl
```

## Failure modes

| Symptom | Check |
| --- | --- |
| Always `AWAITING_HUMAN` | Classification/policy; sensitive paths; unknown class |
| `FAILED` after retries | Evaluation evidence; sandbox errors; retry budget |
| Tool failures | Registry handler errors; path policy |
| Missing audit events | Pass `--audit` or inspect governed store events |

## Safety reminder

Do not claim production reliability from synthetic benchmarks alone.

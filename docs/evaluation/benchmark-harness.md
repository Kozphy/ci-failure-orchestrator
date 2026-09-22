# Foundation benchmark harness (Phase 12)

## Purpose

Answer, reproducibly and locally:

> Does this orchestrator perform correctly, safely, consistently, and without
> regressions across classification, repair, retry, policy, security,
> escalation, audit, and recovery?

This is a **control-plane** benchmark. It is not a claim of production LLM
quality or production incident distribution.

## Dataset philosophy

- Initial dataset is **SYNTHETIC**
- Sample size is limited
- Deterministic planners / scripted proposals by default
- No live LLM / paid API required for the default suite
- No automatic golden expectation updates

## Case schema

See `benchmarks/foundation/README.md` and
`ci_failure_orchestrator/foundation/benchmark/schemas.py`.

## Pipeline

```text
Golden Case
  → Fixture Setup (isolated temp workspace)
  → Orchestrator / Classifier / Tool / Recovery mode
  → Observed Result
  → Expected Assertions
  → Metric Extraction
  → Case Result
  → Benchmark Report (+ optional baseline comparison)
```

## Runner

```bash
python -m ci_failure_orchestrator.cli foundation-benchmark
```

Exit codes:

- `0` — all required cases pass
- `1` — one or more required cases fail / required regression
- `2` — harness / configuration error

## Failure injection

TEST/BENCHMARK ONLY (`benchmark_mode=True`). Supported targets:

- `sandbox`: `timeout`, `error`, `setup_failure`, `patch_failure`
- `evaluator`: `error`, `eval_failure`

## Metrics

See [metrics.md](metrics.md).

## Known limitations

- Synthetic dataset; not production distribution
- Deterministic fakes do not measure real LLM quality
- Security fixtures do not prove complete security
- Local timing is not production latency
- Phase 11 `SecurityFinding` module is not present; security cases assert
  containment via tools, policy, sanitization, and recovery semantics

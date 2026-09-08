# Production Proof Contract

This document defines the minimum evidence required before the CI Failure Orchestrator can claim a production-ready release.

## Release metrics

| Metric | Default threshold | Why it matters |
|---|---:|---|
| Repair success rate | >= 90% | Measures whether attempted repairs actually resolve failures |
| Regression rate | <= 2% | Prevents fixes that introduce new failures |
| P95 latency | <= 30 s | Keeps automated recovery operationally useful |
| Cost per successful repair | <= $0.20 | Prevents uncontrolled agent/tool spend |
| Critical security findings | 0 | Blocks release on critical security risk |

The thresholds are policy defaults, not benchmark claims. Replace `benchmark/production_metrics.example.json` with metrics produced by reproducible benchmark runs before using the result as portfolio evidence.

## Evidence pipeline

```text
Failure corpus
    -> root-cause ranking
    -> repair / verification attempt
    -> evaluator
    -> benchmark metrics
    -> production policy gate
    -> PASS or BLOCK
    -> immutable CI artifact
```

## Reproduce

```bash
python -m pip install -e ".[dev]"
pytest
python scripts/check_production_gate.py benchmark/production_metrics.example.json
```

A successful run writes `artifacts/production-gate.json`. GitHub Actions uploads that file as the `production-proof` artifact.

## Next benchmark increment

The next evidence milestone should replace example metrics with a generated benchmark report containing at least:

- case count and failure taxonomy
- Top-1 and Top-3 root-cause accuracy
- repair success rate
- first-attempt success rate
- regression rate
- mean attempts to resolution
- human escalation rate
- P50/P95 latency
- cost per successful repair
- baseline comparison and confidence intervals where appropriate

## Claim discipline

README figures should be labeled either **measured**, **target**, or **illustrative**. Never present target thresholds or synthetic example values as measured production performance.

# Foundation golden benchmarks (Phase 12)

All cases under `cases/` are **SYNTHETIC** fixtures for local regression of the
foundation control plane. They are **not** measured production evidence and do
**not** represent production incident distribution.

## What is a golden case?

A declarative JSON document with:

- stable `case_id` (e.g. `BENCH-RETRY-001`) — not derived only from filename
- `category` + `tags`
- `required` vs optional
- `fixture` (event, workspace files, scripted proposals, injection)
- `expected` declarative assertions (not arbitrary lambdas)

## Versioning

- Suite: `suite_version` in the harness (`1.0.0`)
- Schema: `foundation.benchmark.v1`
- Each case has its own integer `version`

## Required vs optional

- `required=true` — must pass in CI (exit code 1 on failure)
- `required=false` — experimental / injection / optional tiers

## Expectations review

Golden expectations encode **intended control-plane behavior**, not call-site
implementation details. Changing an expectation requires an explicit developer
edit — the harness never auto-updates goldens.

## Baseline changes

Baseline file: `baselines/current.json`

```bash
python -m ci_failure_orchestrator.cli foundation-benchmark --update-baseline
```

Baseline updates must be intentional and reviewed in PRs. Regressions
(previously passing → failing) fail CI when `--compare-baseline` is used.

## Run

```bash
python -m ci_failure_orchestrator.cli foundation-benchmark
python -m ci_failure_orchestrator.cli foundation-benchmark --category SECURITY
python -m ci_failure_orchestrator.cli foundation-benchmark --case BENCH-SEC-001
python -m ci_failure_orchestrator.cli foundation-benchmark --compare-baseline
```

Reports write to `artifacts/benchmarks/<suite-run-id>/`.

## Tiers

- Tier 1 — deterministic unit/control-plane (default)
- Tier 2 — local integration / failure injection
- Tier 3 — optional model-backed (not required; not included by default)

# Benchmarks

## Governed synthetic suite

All cases under `cases/` are **synthetic fixtures** for local regression of the
governed agent pipeline. They are not measured production evidence.

```bash
ci-orchestrator benchmark --cases benchmarks/cases
```

Each case JSON includes:

- `failure` — FailureEvent fields
- `expected_class` — governed taxonomy label
- `expected_states` — allowed terminal/governance outcomes
- `forbid_success` — optional hard governance assertion

## Foundation golden suite (Phase 12)

See [`foundation/README.md`](foundation/README.md) for the deterministic
control-plane golden dataset (`BENCH-*` case IDs).

```bash
python -m ci_failure_orchestrator.cli foundation-benchmark
```

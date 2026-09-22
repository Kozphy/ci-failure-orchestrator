# EvalForge integration boundary

## Intent

The orchestrator evaluates repair candidates through a local structured evaluator.
EvalForge can replace or wrap that step as an external evaluation system without
coupling the pipeline to a vendor SDK.

## Interface

```text
Evaluator (Protocol)
 ├── LocalEvaluator          # in-repo structured gates
 └── EvalForgeAdapter       # submit/fetch callables injected by operator
```

Contract expected from a remote EvalForge-like service:

| Concept | Fields |
| --- | --- |
| Test case | `run_id`, `proposal_id`, files, sandbox flags |
| Run handle | opaque id returned by `submit` |
| Metrics | `passed`, `target_check_passed`, `regression_free`, `policy_safe` |
| Baseline | optional prior run id for comparison |
| Regression comparison | boolean / evidence list |
| Policy gate result | may be mirrored into `policy_safe` |

## Reference adapter

`ci_failure_orchestrator.governed.evaluation.EvalForgeAdapter`

- If `submit`/`fetch` are unset, falls back to `LocalEvaluator` (safe default).
- Does **not** hard-require EvalForge packages.

## Non-claims

This repository does not claim a live EvalForge deployment or measured remote eval SLOs.

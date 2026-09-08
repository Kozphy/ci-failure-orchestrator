# Level 7 Research Evidence Protocol

This protocol turns CI Failure Orchestrator from a feature-rich platform into a falsifiable, reproducible engineering study.

## Research questions

- **RQ1 — Repair quality:** Does the full orchestrator improve verified repair success over simpler baselines?
- **RQ2 — Safety:** Do evaluator, policy, and retry controls reduce false repairs and regressions?
- **RQ3 — Efficiency:** What cost and latency are paid for additional repair quality and safety?

## Systems under comparison

1. `heuristic_single_attempt` — deterministic/single-attempt baseline.
2. `repair_plus_evaluator` — repair followed by independent evaluation, no retry advantage.
3. `full_orchestrator_retry` — evaluator + bounded retry + stopping/policy controls.

The same frozen corpus, fixtures, environment, and metric definitions MUST be used for all systems. A baseline may not silently receive less context or a different test oracle unless the difference is itself the ablated component.

## Primary outcomes

- verified repair success rate
- false-repair rate
- regression rate

## Secondary outcomes

- Top-1 / Top-3 root-cause accuracy
- escalation rate
- retries per case
- cost per attempted and successful repair
- P50 / P95 latency

## Corpus and split policy

Each case MUST have a stable ID, failure class, fixture/version, expected failing stage, verification oracle, and provenance. Freeze a versioned corpus before a headline run. Do not tune on the held-out evaluation cases. Report counts by failure class so aggregate results cannot hide class imbalance.

Recommended evidence tiers:

- **T0:** synthetic unit fixtures
- **T1:** deterministic repository fixtures
- **T2:** replayed historical CI failures
- **T3:** failures injected into real repositories
- **T4:** shadow-mode live CI observations
- **T5:** controlled production/canary evidence

Claims must name the highest evidence tier actually measured.

## Reproducibility contract

Every published run SHOULD record:

- repository commit SHA
- corpus version and digest
- Python/runtime version
- dependency lock digest
- agent/provider/model identity when applicable
- random seed(s)
- retry, cost, and latency budgets
- exact command/configuration
- per-case raw results
- aggregate results

Generated artifacts belong under `artifacts/benchmark/<run-id>/`; do not hand-edit raw results.

## Statistical reporting

For each system report numerator/denominator as well as rates. For repair success, false repair, and regression, report 95% confidence intervals. For paired systems evaluated on the same cases, report the paired win/loss/tie counts; use a paired binary test such as McNemar's test when sample size is sufficient. Report effect sizes, not only p-values.

Run-to-run stochastic systems SHOULD be repeated across multiple seeds. Keep per-seed outputs and report dispersion rather than selecting the best run.

## Ablation discipline

Each ablation must change one control at a time where feasible. At minimum evaluate:

- no evaluator
- no retry
- no policy gate
- full system

If implementation constraints make a clean ablation impossible, document the confound instead of presenting the result as causal evidence.

## Failure taxonomy

Every unsuccessful case MUST receive one terminal category:

- `rca_miss`
- `planner_miss`
- `executor_failure`
- `verification_failure`
- `regression`
- `budget_exhausted`
- `policy_blocked`
- `human_escalation`
- `environment_failure`
- `unknown`

Keep `unknown` visible; never redistribute unknown failures to improve metrics.

## Threats to validity

A benchmark report MUST discuss at least:

- synthetic-to-real-world gap
- corpus selection and class imbalance
- leakage/tuning on evaluation cases
- provider/model drift
- nondeterminism
- verification-oracle quality
- cost measurement assumptions
- external validity across languages, CI providers, and repository sizes

## Headline-claim gate

A result may be called **Level 7 evidence** only when:

1. the corpus is versioned and frozen;
2. at least one meaningful baseline is run on the identical corpus;
3. per-case raw outputs are retained;
4. confidence/uncertainty is reported;
5. ablations are run and their confounds documented;
6. failure taxonomy and threats to validity are published;
7. a clean checkout can reproduce the benchmark command;
8. measured results are clearly separated from examples or simulated values.

Until these conditions are met, README numbers must be labeled illustrative, fixture-only, or preliminary as appropriate.

## Suggested benchmark report

```text
commit: <sha>
corpus: <version + digest>
environment: <runtime/lock digest>

system                     n   repair% [95% CI]  false%  regress%  p95_ms  cost
heuristic_single_attempt   ...
repair_plus_evaluator      ...
full_orchestrator_retry    ...

paired comparison: wins / losses / ties
failure taxonomy: counts by terminal category
ablation notes: ...
threats to validity: ...
reproduction command: ...
```

The goal is not to maximize a single number. The goal is to make the system's claims independently checkable.
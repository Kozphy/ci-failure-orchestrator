# Executable Research Experiment Protocol

This protocol turns the research-readiness roadmap into falsifiable, reproducible experiments. It defines the minimum evidence needed before CI Failure Orchestrator may claim support for RQ1-RQ4.

## Scope

The first milestone is **RQ1: dependency-aware diagnosis**.

> Does dependency-aware failure analysis improve root-cause identification over rule-based and log-only baselines?

The existing synthetic corpus is useful for pipeline validation but is not sufficient by itself for a research-quality external claim. Synthetic, fixture, and real-world evidence must remain labeled separately.

## Hypotheses

### H1 — Diagnosis quality

Dependency-aware methods improve root-cause top-1 accuracy over log-only baselines.

### H2 — Robustness

The improvement persists across more than one failure category and is not driven by a single dominant class.

### H3 — Efficiency trade-off

Any accuracy improvement must be reported together with latency and cost rather than treated as free.

## Frozen baseline set

Use `baselines/registry.json` as the canonical registry.

```text
B0  Rule / keyword
B1  LLM + bounded logs
B2  LLM + bounded repository context
B3  Dependency graph without LLM
B4  Dependency graph + LLM
P   Full proposed system
```

For RQ1, B0-B4 are the primary comparison set. The full repair system P may be included, but diagnosis claims must not depend on repair-stage information unavailable to the baselines.

## Dataset contract

Every new research case should satisfy `benchmark/research_case.schema.json`.

Minimum target for the first publishable benchmark:

```text
200 <= N <= 500 validated cases
```

Recommended stratification:

- dependency
- syntax / compilation
- lint / formatting
- unit test
- integration test
- configuration
- security / policy
- flaky / nondeterministic
- timeout / resource
- cross-job dependency

Do not force equal class sizes when that would make the corpus artificial. Publish class counts and use macro metrics so dominant classes cannot hide weak minority-class performance.

## Split policy

```text
TRAIN / DEVELOPMENT
    ↓
method and prompt iteration allowed

TEST
    ↓
frozen before final evaluation

HOLDOUT
    ↓
optional external or later validation
```

Once the final test evaluation begins, do not modify a method using test-set failures and continue reporting it under the same version.

## Run protocol

For every method and stochastic seed:

1. Resolve benchmark version and immutable digest.
2. Resolve repository commit SHA.
3. Resolve method/baseline version.
4. Pin provider/model/prompt/configuration where applicable.
5. Run the exact frozen case set.
6. Record one row per case in immutable raw results.
7. Record failures, timeouts, refusals, and missing outputs rather than silently dropping them.
8. Compute metrics from raw results with deterministic analysis code.
9. Preserve the experiment manifest and artifact digests.

Start with at least 5 repeated seeds for stochastic methods when cost permits. Increase repetitions if confidence intervals are unstable.

## Raw result contract

One result per benchmark case should contain at minimum:

```text
experiment_id
case_id
method_id
predicted_root_cause
ground_truth_root_cause
ranked_candidates
confidence_if_available
correct_top1
correct_topk
latency_ms
input_tokens_if_available
output_tokens_if_available
cost_usd_if_available
status
error_type_if_failed
```

Do not infer missing cost, token, or latency fields as zero.

## Primary metrics

### Primary endpoint

- root-cause top-1 accuracy

### Secondary endpoints

- top-3 accuracy
- macro precision
- macro recall
- macro F1
- per-class F1
- latency distribution
- API/token cost
- failure / timeout rate

If confidence scores are comparable across methods, also report calibration metrics.

## Statistical analysis

For the same benchmark cases, prefer paired analysis.

Minimum reporting standard:

```text
point estimate
+ 95% confidence interval
+ paired difference versus baseline
+ effect size where meaningful
+ exact N used
+ missing/failed run policy
```

For paired binary correctness outcomes, McNemar-style comparison is a reasonable candidate. For metric differences estimated by resampling, paired bootstrap confidence intervals are a reasonable candidate. The final test must be chosen based on actual assumptions and data distribution rather than hard-coded in advance for every metric.

Correct for multiple comparisons when testing many methods/hypotheses.

## Ablation protocol

After establishing the full method result, run controlled removals:

```text
FULL
-GRAPH
-MEMORY
-INDEPENDENT_VERIFICATION
-CANDIDATE_TOURNAMENT
-SUPERVISOR_POLICY
-SINGLE_AGENT vs MULTI_AGENT
```

For each ablation, change one major component at a time when possible and preserve all other configuration.

Report whether the component primarily changes:

- diagnosis quality
- repair quality
- safety
- latency
- cost
- escalation rate

## Failure analysis

Every incorrect or incomplete outcome should map to one or more categories:

```text
incorrect_diagnosis
insufficient_evidence
hallucinated_dependency
invalid_patch
test_weakening
hidden_regression
flaky_verification
policy_violation
security_violation
budget_exhaustion
verifier_disagreement
unknown
```

Publish aggregate frequencies plus representative examples with sensitive or copyrighted material bounded appropriately.

## Claim levels

```text
CLAIM_LEVEL_0 = ARCHITECTURE_ONLY
CLAIM_LEVEL_1 = SYNTHETIC_VALIDATION
CLAIM_LEVEL_2 = VERSIONED_BENCHMARK_RESULT
CLAIM_LEVEL_3 = STATISTICALLY_VALIDATED_COMPARISON
CLAIM_LEVEL_4 = ABLATION_AND_FAILURE_ANALYSIS
CLAIM_LEVEL_5 = INDEPENDENT_REPRODUCTION
```

A claim must never be presented at a higher level than its evidence supports.

## RQ1 completion gate

```text
RQ1_EVIDENCE_READY =
BENCHMARK_VERSION_FROZEN
AND CASE_PROVENANCE_VALID
AND BASELINES_VERSIONED
AND TEST_SPLIT_FROZEN
AND RAW_RESULTS_IMMUTABLE
AND METRICS_REPRODUCIBLE
AND CONFIDENCE_INTERVALS_REPORTED
AND PAIRED_BASELINE_COMPARISON_COMPLETE
AND PER_CLASS_ANALYSIS_COMPLETE
AND FAILURE_ANALYSIS_COMPLETE
AND CLAIMS_MATCH_EVIDENCE
```

## Next implementation tasks

1. Write a validator for `benchmark/research_case.schema.json`.
2. Add adapters that convert current corpus formats into the research-case contract without overwriting source data.
3. Implement B0 first as a deterministic baseline runner.
4. Implement a generic experiment runner that writes `experiments/manifest.example.json`-compatible manifests.
5. Write deterministic metric computation from raw JSONL results.
6. Add paired bootstrap confidence intervals.
7. Add an RQ1 report generator that builds tables from artifacts rather than hard-coded README values.

The immediate goal is not to claim research readiness. It is to make the first RQ1 result independently inspectable and falsifiable.

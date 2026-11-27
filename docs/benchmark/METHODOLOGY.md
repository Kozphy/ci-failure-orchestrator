# Benchmark methodology

Two benchmarks are specified. The v1 files in this repository implement only the synthetic subset. External cases are listed and not scored.

## 1. Root-cause diagnosis

**Question.** Given a set of failed pipeline stages, which stage is the root cause?

**Population for v1.** The 8 cases in `benchmark/ci_failure_corpus.v1.json`. Author-written. No other diagnosis case is in this denominator.

**Outcome per case.** Top-1 is correct when the system's first stage equals `root_cause`. Top-3 is correct when `root_cause` is among the first three. A case with no prediction is incorrect. It is not dropped.

**Skipped and timed out.** The v1 scripts have no skip and no timeout. A future case may be `excluded` only when the exclusion is written to the result with a reason. An excluded case stays in the published denominator as excluded. It is not counted as correct.

**Systems.**

| Id | v1 status | Definition |
| --- | --- | --- |
| B0 | Executable | Latest visible failed stage. |
| B3 | Executable | Dependency-graph ranker (`run_baseline` / `evaluate_corpus`). |
| B1, B2, B4 | Not executable here | Log-only model, model plus context, model plus graph. The legacy runner raises. They are not given a score of zero. |

**Split.** v1 has one split: the whole file. There is no development/test/holdout partition. Held-out evaluation is not claimed.

**Oracle.** The `root_cause` field was written by the corpus author with the case. It is not independent of the person who built the ranker.

## 2. Repair verification

**Question.** Does the deterministic repair loop make the fixture tests pass without a detected regression, inside the retry budget?

**Population for v1.** The 4 cases in `benchmark/repair_fixture_corpus.v1.json`.

**Outcomes.**

| Metric | Numerator | Denominator |
| --- | --- | --- |
| Repair success | Runs whose final state is resolved | All runs, including unresolved |
| First-attempt success | Runs whose first attempt succeeds and has no regression flag | All runs |
| Regression rate | Attempts with `regression_detected` | All attempts, not all runs |
| Escalation rate | Runs the loop marks escalated | All runs |

A timed-out or crashed attempt is an unsuccessful attempt. It remains in both denominators. It is not removed from the published set.

**Oracle.** The fixture's own `test_app.py` (or equivalent) is the visible check. v1 has no hidden regression test stored outside the fixture tree. A patch can edit the visible test. That is a known hole, not a passed hidden-oracle check.

**Hidden tests, when they are added.** A hidden oracle file must live outside the fixture directory that the patch is allowed to edit. The runner rejects a patch whose diff touches the oracle path, and the oracle command must show that its tests actually ran. A green visible suite with a skipped oracle is not a pass. The research repair harness on branch `research/rq1-artifact` is the existing implementation of that rule. This benchmark does not reimplement it.

## Versioning

- Corpus version is the `version` field plus the LF SHA-256 published in `docs/benchmark/GAP_ANALYSIS.md`. CRLF in a working tree is normalized before that hash.
- A corpus change that alters a case, a label, or a file hash requires a new version string. Checksums in `tests/test_offline_benchmark_evidence.py` must be updated in the same change.
- Baseline code changes do not rewrite old result files under `artifacts/`. Those files are gitignored local outputs.

## Held-out contamination

v1 cannot be contaminated by holdout tuning because it has no holdout. The matching limit is the opposite: the same author wrote the cases, the ranker and the test that requires the ranker to beat B0. Results from v1 are development evidence.

A later holdout split must be hashed before any prompt, rule or threshold is changed in response to it. Cases move into holdout only by an explicit manifest edit. The default offline command must refuse to score a split named `holdout` unless a separate confirmation flag is present.

## External cases

`benchmark/external_cases.v0.json` is a candidate queue. Each row has a repository, SPDX license, workflow run URL, numeric run id, and `head_sha` observed from the GitHub API on 2026-10-19. `ground_truth` is null. A case enters the scored denominator only after an independent reviewer, who did not write the scorer for that case, records a label and the evidence they used. Ambiguous failures stay unlabelled.

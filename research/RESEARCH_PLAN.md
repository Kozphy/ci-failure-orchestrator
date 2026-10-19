# Research plan

This is the canonical research plan for `ci-failure-orchestrator`. It supersedes the research-question
lists in `docs/research/research-readiness.md`, `docs/research/experiment-protocol.md` and
`docs/research_protocol.md`, which are kept for history and point here.

## Research questions

**RQ1 (primary).** Does independent verification plus policy gating reduce incorrect CI repairs
compared with simpler automated CI-diagnosis and repair approaches?

**RQ2 (secondary).** How much do repository context, dependency information and independent
verification improve CI root-cause diagnosis and verified repair quality?

## Hypotheses (not findings)

- **H1 (RQ1).** On cases with labelled repair candidates, the product pipeline (P) accepts fewer
  incorrect repairs than a system that accepts the first candidate that turns CI green (R-GREEN),
  at the cost of more human escalations.
- **H2 (RQ1).** Removing the policy gate or the independent verification step from P raises the
  incorrect-acceptance rate. Removing the retry budget lowers the correct-repair rate.
- **H3 (RQ2).** Dependency-graph ranking (B3) identifies the root-cause stage more often than the
  latest visible failure (B0) on multi-stage cascades.
- **H4 (RQ2).** Adding bounded repository context (B2) or dependency information (B4) to a log-only
  model (B1) improves failure-class and root-cause accuracy. This is untested until a real model
  is run; see `research/CLAIMS.md`.

None of these is supported until `research/CLAIMS.md` says so with a linked experiment ID.

## Audit (2026-10-07, before this change)

### Existing capabilities that are reused, not duplicated

| Capability | Where | Used for |
| --- | --- | --- |
| Canonical verification semantics (`VerificationResult`, `decide_remediation`, `is_verified_fix`) | `ci_failure_orchestrator/foundation/remediation.py` | The VERIFIED_FIXED and locally-verified definitions |
| Before/after worktree verification (exact target rerun, regression, test counts, skips/xfail, waivers, integrity, diff risk) | `ci_failure_orchestrator/service/verification.py` | Evidence for every repair candidate |
| End-to-end repair run (reproduce, propose, retry budget, policy, verification) | `ci_failure_orchestrator/service/run.py` (`run_fix_repo`) | System P on the repair track |
| Deterministic policy engine | `ci_failure_orchestrator/foundation/policy.py` | Policy gate inside P |
| Verification-integrity analysis (skips, xfail, deleted tests, weakened gates) | `ci_failure_orchestrator/foundation/verification_integrity.py` | Fake-fix detection inside P |
| Rule-based failure classifier (uncalibrated) | `ci_failure_orchestrator/foundation/classifier.py` | Failure class for B0, B3 and P |
| Dependency-graph root-cause ranker | `ci_failure_orchestrator/ranker.py`, `corpus_benchmark.py` | B3 and P diagnosis |
| Baseline registry with fail-closed runner | `baselines/registry.json`, `ci_failure_orchestrator/baselines.py` | Baseline contracts and versions |
| Wilson intervals, paired comparison, bootstrap, exact McNemar, canonical digests | `research_stats.py`, `research_evaluation.py` | Uncertainty and paired tests |
| Sandboxed provider runner (no shell, env allowlist, timeout, output cap) | `ci_failure_orchestrator/provider_adapters.py` | The `command` model provider |

### Missing research capabilities (before this change)

- No dataset in the research-case schema, no splits, no hashes, no validator, no leakage checks.
- B1, B2 and B4 were contracts only, with no provider abstraction and no versioned prompts.
- No repair-track experiment with ground truth that is independent of the system under test.
- No experiment manifest written by a runner, no immutable raw outputs, no processed tables.
- No error taxonomy, claim registry, external-validation ladder or maintainer validation pack.

### Duplicated benchmark structures

- `benchmark/` holds research and repair corpora (cascade corpus, repair fixtures, merge corpora,
  the research-case schema).
- `benchmarks/` holds control-plane regression goldens (`benchmarks/foundation/` BENCH-* cases,
  `benchmarks/cases/`, `benchmarks/corpus/v0.1.jsonl`).
- `benchmarks/cases/01..08` repeat `BENCH-CLASS-*` fixtures almost verbatim.

Decision: both directories stay where they are, because existing tests and scripts read them. The
new research dataset lives in `research/datasets/` and is built from them, plus the authored cases
in `research/authored_cases.py`, by a deterministic builder (`python -m research.build_dataset`). The
builder removes duplicates and records every exclusion in `research/datasets/exclusions.json`. See
`research/README.md` for the directory map.

### Inconsistencies

- Three documents define "RQ1" differently: diagnosis ranking, repair quality, and a numbered
  "Level 7" protocol. They also use three evidence ladders (claim levels 0-5, tiers T0-T5, E-labels
  in `evidence/README.md`). The canonical ladder is now E0-E7 in `research/EXTERNAL_VALIDATION.md`.
- The schema split enum (`train/dev/test/holdout`) did not match the frozen split names required
  here (`development/test/holdout`). Schema 1.1 accepts both and the validator normalises them.
- `repair_state_machine.VerificationResult` is a second, non-canonical verification type.
  Research code uses only `foundation.remediation`.
- `evidence/README.md` labels controlled local runs "E4-simulated". On the ladder used here they
  are E0 (synthetic).

### Gaps that blocked RQ1

1. No ground truth for repair correctness that the system under test cannot see. Fixed by hidden
   oracle tests stored outside the fixture repository and used only for scoring.
2. No simpler repair comparator. Fixed by R-GREEN (accept the first candidate that turns CI green).
3. No way to run the real P on scripted candidates. Fixed by an optional, backwards-compatible
   `source` field on `FixRepoConfig`; nothing else in the product changes.
4. No paired per-case outcomes for McNemar or bootstrap. Fixed by the runner.

### Minimum changes made

- `research/` package: schema validation, dataset import, splits and lock file, baselines B0-B4
  and P, providers, repair harness, metrics, statistics, manifest, runner, reports, collector.
- `benchmark/research_case.schema.json` upgraded to schema 1.1, which stays compatible with 1.0
  cases.
- `FixRepoConfig.source` (optional) in `ci_failure_orchestrator/service/run.py`.
- `baselines/registry.json` updated to the real implementation status.
- Research tests, a research CI workflow job, documentation, `CITATION.cff`.

No new services, databases, control planes or runtime dependencies.

## Phases

1. Audit, plan, schema, splits and leakage controls, metric definitions, manifest.
2. Baselines B0 and B3 on research cases, then B1, B2 and B4 through the provider abstraction,
   then the P adapter.
3. Runner, metrics, confidence intervals, ablations, error analysis, results.
4. Manuscript, claims registry, reproducibility guide, README evidence section.
5. Public OSS collector, maintainer validation pack, pilot protocol, external-validation registry.

## Deviations log

Every departure from this plan is recorded here, including ones that weaken the evidence.

| Date | Deviation | Effect | Response |
| --- | --- | --- | --- |
| 2026-10-07 | While smoke-testing the diagnosis code, the developer saw B0, B3 and the mock provider's class and root-stage results on the **test** split before the dataset was frozen. | The test split is no longer fully unseen for diagnosis. Prompts, rules and cases could in principle have been tuned to it. | Nothing was changed in response: no prompt, rule, classifier or case was edited after the exposure. The exposure is listed in `THREATS_TO_VALIDITY.md`. The holdout split is empty and will be the first unseen evaluation. |
| 2026-10-07 | The first default run (`rq1-rq2-test-20261007T121729Z-6a88f15b`) recorded `git_dirty: true` because git state was read at the end of the run, after unrelated edits made while it ran. | Its manifest does not prove which tracked files were loaded. The process imported code at start from commit `5648187`. | The runner now records git state at start. The run was repeated from a clean commit; both raw directories are kept, and `research.compare_runs` checks that they agree. |
| 2026-10-07 | Target case counts (40 synthetic, 30 own-repository, 50 public OSS, 30 holdout) were not met. | Only synthetic and fixture cases exist: 40 development, 26 test, 0 holdout, 0 real-world. | No cases were invented. Real-world collection is future work (`research/collect_oss.py`, `research/EXTERNAL_VALIDATION.md`). |

## Definition of done (research)

- [x] `python -m research.validate_dataset` passes on the committed dataset and lock file.
- [x] `python -m research.run --config research/config/smoke.yaml` passes without credentials.
- [x] `python -m research.run --config research/config/default.yaml` produces a manifest, raw
      outputs and processed tables, with every case ID recorded.
- [x] Every metric in `research/METRICS.md` is either computed or reported as `null` with a reason.
- [x] Every row in `research/CLAIMS.md` that says SUPPORTED cites an experiment ID whose raw
      outputs are committed (checked by `python -m research.claims`).
- [x] The holdout split has not been read by any tuning step (it is empty; the runner refuses it
      without `allow_holdout` and `--confirm-holdout`).
- [x] Limitations are stated in the README, the manuscript and the dataset card.
- [ ] B1, B2 and B4 run with a claim-eligible model provider. **Not done.**
- [ ] Real-world cases (own repository and public OSS) labelled and frozen. **Not done.**
- [ ] At least one external-validation event at E2 or above is recorded. **Not done.**

## External-phase checklist

- [ ] Collect public OSS failure candidates with `python -m research.collect_oss` (unlabelled queue).
- [ ] Label them with `research/ANNOTATION_PROTOCOL.md`; second annotator on at least 20%.
- [ ] Freeze a new dataset version with a non-empty holdout split.
- [ ] Run B1, B2 and B4 with a recorded model provider; commit the recordings.
- [ ] Send maintainer packs (`research/maintainer_pack/`) only after a human decides to; never automatically.
- [ ] Record each external event in `research/external_validation_registry.json`.
- [ ] Re-run the default experiment on the new version, then evaluate the holdout split once.

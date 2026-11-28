# Benchmark gap analysis

Audit date: 2026-10-19. Measurement commit: `4410e3ab881770c5d228bee84cb9255c04e2475d`.
The two corpus files below are byte-identical on `origin/main` (`f7b6cf2`); `git diff origin/main` for this audit touched only `benchmark/research_case.schema.json` among benchmark inputs.

This file records commands that were run. It does not fill in results for commands that were not run.

## Environment

| Item | Value |
| --- | --- |
| Python | 3.14.6 (`python --version`) |
| Package install | Not installed in that interpreter. `python scripts/run_baseline_matrix.py` exited 1 with `ModuleNotFoundError: No module named 'ci_failure_orchestrator'`. |
| Reproduction used | `PYTHONPATH` set to the repository root. CI installs `pip install -e ".[dev]"` instead. |
| PyYAML | 6.0.2 |
| pytest | 9.1.1 |
| Lockfile | None. `requires-python` is `>=3.10`. |
| Live LLM credentials | Not used. |

CI workflows for these benchmarks request Python 3.11 (`research-evidence.yml`) or 3.12 (`repair-benchmark.yml`, `foundation-benchmark.yml`). Those interpreters were not used for the numbers below.

## Commands and exit codes

| Command | Exit |
| --- | --- |
| `python scripts/run_baseline_matrix.py` (default B0, B3) | 0 |
| `python scripts/run_research_rq1.py` | 0 |
| `python scripts/run_corpus_benchmark.py benchmark/ci_failure_corpus.v1.json` | 0 |
| `python scripts/run_repair_fixture_benchmark.py benchmark/repair_fixture_corpus.v1.json` | 0 |
| `python scripts/run_baseline_matrix.py --baselines B1` | 1. `ValueError: Unsupported executable baseline 'B1'; supported: B0, B3` |
| `pytest` on `test_corpus_benchmark.py`, `test_repair_benchmark.py`, `test_research_evaluation.py`, `test_baselines.py`, `test_foundation_phase_12_benchmark.py` | 0. 29 tests collected (18 + 4 + 3 + 3 + 1). |

`foundation-benchmark` was not run in this audit.

## Corpus checksums

| File | Cases | LF SHA-256 (git blob bytes) |
| --- | --- | --- |
| `benchmark/ci_failure_corpus.v1.json` | 8 | `a8e6c2e2ba19574a3e3b9faa4327a58c03be30d11e39b790430da96413dadf22` |
| `benchmark/repair_fixture_corpus.v1.json` | 4 | `0a6f1ff41327c9869faad9aa2ca5e23974d3449f5b88e57f790f050f7604211a` |

The 2026-10-19 audit machine had `core.autocrlf=true`, so a raw hash of the working tree was the CRLF hash `1897b663e92c8420ff545f44aa05ee70b5be7aa3b463b21d3302bb5d62bb2f05` for the diagnosis corpus and `71a2fe09ec7338013bfaa9d5d6918e7fb8e86811fb0faa4ddaba7d6a4c93a93b` for the repair fixtures. Ubuntu CI checks out LF and recorded `a8e6c2e2…`. The envelope and the integrity test use the LF digest.

`run_research_rq1.py` records a different digest, the canonical JSON digest `8c9cc089c51b58d1076e4a025d9c5f10117d95368b647df9c634b923724b94d1`. Both are real. They hash different byte strings. A reader cannot treat them as the same identifier.

`benchmarks/foundation/` holds 38 golden case files plus `baselines/current.json`. Those cases are a control-plane regression suite, exercised by `tests/test_foundation_phase_12_benchmark.py`, not by the corpus scripts.

## Measured synthetic results

Diagnosis corpus, 8 author-written cascade cases. Every case is in the scored denominator. There is no skip and no timeout path in these scripts.

| System | Top-1 | Source |
| --- | --- | --- |
| B0 latest visible failure | 0.125 (the matrix and the corpus script agree) | `baseline-matrix.json`, `corpus-benchmark.json` |
| B3 dependency-graph ranker | 1.0 | same |
| Corpus top-3 | 1.0 | `corpus-benchmark.json` |
| Mean cascade elimination | 0.9583 | `corpus-benchmark.json` |

RQ1 paired comparison on the same 8 cases (`rq1.json`, seed `20260910`, 10,000 bootstrap trials): proposed accuracy 1.0, baseline accuracy 0.125, absolute uplift 0.875, 95% bootstrap interval 0.625 to 1.0, 7 discordant pairs all won by the proposed ranker, exact McNemar p = 0.015625. The script's own `evidence_type` is `paired_reproducible_synthetic_benchmark`.

Repair fixtures, 4 author-written cases, retry budget 2:

| Metric | Value | Denominator in code |
| --- | --- | --- |
| Repair success | 1.0 | resolved runs / 4 runs |
| First-attempt success | 0.75 | 3 / 4 runs |
| Mean attempts | 1.25 | attempts / runs |
| Regression rate | 0.2 | attempts with `regression_detected` / 5 attempts |
| Escalation rate | 0.0 | escalated runs / 4 runs |

The one `regression_detected` attempt is the first, intentionally wrong candidate of `retry-then-success`. The rate is not "20% of cases regressed."

## What is synthetic, and what is not

| Input | Evidence class |
| --- | --- |
| `benchmark/ci_failure_corpus.v1.json` | Synthetic. The file says so in `description`. |
| `benchmark/repair_fixture_corpus.v1.json` | Synthetic fixtures written in this repository. |
| `benchmarks/foundation/` | Author-written goldens for the control plane. |
| `benchmark/external_cases.v0.json` | Ten public workflow runs with verified URLs, licenses and head SHAs. **No root-cause label. None were executed.** |

No independently labelled external case was scored by the runners above.

## Gaps

1. **Two diagnosis runners, one corpus.** `run_corpus_benchmark.py` and `run_baseline_matrix.py` both score B0 against the ranker. Their accuracy numbers matched on this run. Their file formats and checksum algorithms do not.
2. **B1, B2 and B4 are not executable** in `ci_failure_orchestrator/baselines.py`. Asking for B1 aborts the process. The research branch `research/rq1-artifact` records those systems as `NOT_RUN` instead. This PR does not copy that runner.
3. **`repair-benchmark.yml` does not run the repair-fixture script.** It runs `tests/test_repair_benchmark.py` (one in-memory control-plane case pair) and `tests/test_control_plane.py`.
4. **No held-out split** on the v1 corpora. Every case is visible to the author and to the tests, and `test_causal_ranker_beats_latest_visible_baseline_on_corpus` asserts the ranker is at least as accurate as the baseline. That test cannot discover a regression in which the ranker falls behind.
5. **Failed, skipped and timed-out diagnosis cases have no denominator.** The scripts score every case in the file. An empty prediction list becomes accuracy `0.0` in `run_baseline_matrix.py`, which is a reported number, not a missing result.
6. **Repair regression uses a different denominator from repair success.** Publishing either number without the denominator overstates it.
7. **Checksums disagree** (raw bytes versus canonical JSON), and the result JSON includes a timestamp (`generated_at_utc` in `rq1.json`), so two identical scores do not have identical result hashes.
8. **No lockfile.** A later dependency resolve can change repair timing and, if a scorer changes, the rates.
9. **Import path.** A clean tree without an editable install cannot run the scripts. The offline envelope in this change sets `PYTHONPATH` for its children. The original scripts are unchanged.
10. **External cases are a queue, not a result.** Labels require independent review. Logs were not downloaded, because job logs for other repositories are not a default read of this audit.

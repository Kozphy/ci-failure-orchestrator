# Reproduce the offline benchmarks

Clean-room path. No API key, no model credential, no network call during scoring.

## One command

From a fresh clone, with Python 3.10 or newer:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python scripts/run_offline_benchmark.py --output-dir artifacts/benchmarks/offline
```

macOS or Linux:

```bash
source .venv/bin/activate
python -m pip install -e ".[dev]"
python scripts/run_offline_benchmark.py --output-dir artifacts/benchmarks/offline
```

Exit 0 means every existing script exited 0 and wrote a non-empty file. Exit 1 means the envelope status is `FAILED`. A missing file is a failure even when a script exits 0.

Outputs, all gitignored under `artifacts/`:

- `artifacts/benchmarks/offline/evidence.json` (schema `benchmark/evidence.schema.json`)
- `artifacts/benchmarks/offline/evidence.md`
- `baseline-matrix.json`, `rq1.json`, `corpus-benchmark.json`, `repair-fixture-benchmark.json`

The envelope sets `PYTHONPATH` to the repository root for its children and strips `GITHUB_TOKEN` and `GH_TOKEN`. The original scripts are still the scorers.

## Existing commands, unchanged

```bash
python scripts/run_baseline_matrix.py --output artifacts/research/baseline-matrix.json
python scripts/run_research_rq1.py --output artifacts/research/rq1.json
python scripts/run_corpus_benchmark.py benchmark/ci_failure_corpus.v1.json --output artifacts/corpus-benchmark.json
python scripts/run_repair_fixture_benchmark.py benchmark/repair_fixture_corpus.v1.json --output artifacts/repair-fixture-benchmark.json
python -m pytest -q tests/test_corpus_benchmark.py tests/test_repair_benchmark.py tests/test_research_evaluation.py tests/test_baselines.py tests/test_foundation_phase_12_benchmark.py tests/test_offline_benchmark_evidence.py
```

`run_baseline_matrix.py --baselines B1` is expected to exit 1 on this revision. That is the unsupported-baseline error, not a score.

## What the numbers are allowed to mean

The envelope's `measurements.evidence_class` is `synthetic_fixture`, and `independently_labelled_cases` is 0. Quoting a top-1 accuracy from this run as a production or external result contradicts the envelope.

Seeds already fixed by the existing RQ1 script: `--seed 20260910`, `--bootstrap-trials 10000`. The offline command does not override them.

## Dependency note

There is no lockfile. The audit that produced `docs/benchmark/GAP_ANALYSIS.md` used Python 3.14.6, PyYAML 6.0.2 and pytest 9.1.1. GitHub Actions for the related workflows use 3.11 or 3.12. Record `platform.python_version()` from `evidence.json` next to any number you cite.

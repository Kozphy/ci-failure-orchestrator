# Benchmarks

The offline reproduction command and the evidence rules are in [REPRODUCE.md](REPRODUCE.md).

| Document | What it is |
| --- | --- |
| [GAP_ANALYSIS.md](GAP_ANALYSIS.md) | Commands run on 2026-10-19, exit codes, checksums, and synthetic results |
| [METHODOLOGY.md](METHODOLOGY.md) | Denominators, baselines, oracles, holdout rule |
| [LIMITATIONS.md](LIMITATIONS.md) | What these numbers do not show |
| [REPRODUCE.md](REPRODUCE.md) | Clean-room commands |

Scorers stay in the existing scripts: `scripts/run_baseline_matrix.py`, `scripts/run_research_rq1.py`, `scripts/run_corpus_benchmark.py`, `scripts/run_repair_fixture_benchmark.py`. `scripts/run_offline_benchmark.py` only runs them and refuses to call a missing output a success.

External candidates, unlabelled: `benchmark/external_cases.v0.json`.

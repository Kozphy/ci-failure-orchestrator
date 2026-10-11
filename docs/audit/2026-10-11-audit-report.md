# Reproducibility audit: `Kozphy/ci-failure-orchestrator` @ `f7b6cf2`

- **Date:** 2026-10-11 (Asia/Taipei, UTC+8)
- **Revision audited:** `f7b6cf2e65b3d2ef3f15cecb4fc1c65874c3f56f` ("docs: add AI agent production roadmap and upgrade prompt", 2026-10-05). `git rev-parse HEAD` after checkout returned exactly this SHA.
- **Scope:** run the focused CI-audit tests and the full suite with coverage, run a read-only public-repository audit with the tool itself, and record the results. **No application code, tests, CI workflows or dependency pins were changed.** This document and the files under `2026-10-11-evidence/` are the only additions.
- **Raw evidence:** [`2026-10-11-evidence/`](2026-10-11-evidence/). Reproduce with [`reproduce-audit.sh`](reproduce-audit.sh).

## Summary

| Check | Result |
|---|---|
| Focused CI-audit tests (`tests/test_ci_audit.py`) | **18 passed**, 0 failed, 0 skipped, 0 errors (0.37 s) |
| Full suite, run 1 (venv python, but no `python` on `PATH`) | **3 failed**, 816 passed, 0 skipped, 0 errors, 1 warning (43.92 s) — environment cause, see below |
| Full suite, run 2 (venv on `PATH`, as in CI) | **819 passed**, 0 failed, 0 skipped, 0 errors, 1 warning (41.89 s) |
| Full suite, repeat run (no coverage) | 819 passed, 1 warning (34.27 s) |
| Coverage (run 2) | **86%** combined (statements + branches); line rate 89.05% (12,904 / 14,491), branch rate 73.7% |
| Coverage of `ci_audit/` from focused tests alone | 92% combined |
| ci.yml lint / docstring / mypy / trust tests / smoke | all pass (ruff, ruff D-rules, mypy 6 files, 23 trust tests, `rank` smoke) |
| Public audit (unauthenticated, read-only) | `COLLECTED`: 30 runs, 40 jobs, 2 failed jobs, 1 warning (job logs need admin → HTTP 403) |
| Upstream CI at this exact SHA (from the public audit) | `ci` run 37332637994 **failed** in job `server-image` (Compose smoke test); `test` and `server-postgres` jobs passed |

## Environment

| Item | Value |
|---|---|
| OS | Debian GNU/Linux 13 (trixie), kernel 6.12.94+ x86_64, GNU bash |
| System Python | 3.13.5 (`python3` only; **no `python` executable on `PATH`**) |
| Test Python | CPython 3.12.15 (matches `python-version: '3.12'` in `ci.yml`) |
| Environment tool | uv 0.12.23 (`uv venv`, `uv pip`) |
| Key packages | pytest 9.1.1, pytest-cov 7.1.0, coverage 7.16.2, fastapi 0.143.0, sqlalchemy 2.1.4, pydantic 2.14.0, httpx 0.28.1, PyYAML 6.0.3, ruff 0.17.0, mypy 2.4.0 |
| Full freeze | [`pip-freeze.txt`](2026-10-11-evidence/pip-freeze.txt) (40 packages) |
| Lockfile | **None in the repository** (only lower bounds in `pyproject.toml`), so versions above are whatever resolved on 2026-10-11 |
| Docker | Not available on the audit machine |
| PostgreSQL | Not available; `TEST_DATABASE_URL` unset |

Install commands:

```bash
git clone https://github.com/Kozphy/ci-failure-orchestrator.git
cd ci-failure-orchestrator
git checkout f7b6cf2e65b3d2ef3f15cecb4fc1c65874c3f56f
git rev-parse HEAD   # f7b6cf2e65b3d2ef3f15cecb4fc1c65874c3f56f
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[dev,server]'   # same extras as ci.yml "test" job
```

## How the focused CI-audit tests were chosen

- The repository has no custom pytest markers (only `parametrize`), so selection is by module.
- The read-only CI reliability audit lives in `ci_failure_orchestrator/ci_audit/` (`collect.py`, `analyze.py`, `report.py`), exposed as `ci-orchestrator ci-audit-collect` / `ci-audit-report` (`docs/ci-reliability-audit.md`, `docs/ENGINEERING.md`, `docs/module-status.md`).
- `tests/test_ci_audit.py` is the only test module importing `ci_audit`; it covers collection, secret scrubbing, analysis, report rendering, pagination, token-dropping on log redirects and the two CLI commands.
- Not included: `tests/test_audit.py` (the JSONL audit *log*, a different feature) and `tests/test_doctor*.py` (the `actions-doctor` diagnosis). Both still ran in the full suite.

## Focused run

```bash
.venv/bin/python -m pytest tests/test_ci_audit.py -v -rA -p no:cacheprovider
```

Result: `18 passed in 0.37s` (log: [`focused-ci-audit.log`](2026-10-11-evidence/focused-ci-audit.log)).

Focused coverage of the module (`--cov=ci_failure_orchestrator.ci_audit`, 18 passed in 0.50 s):

| File | Stmts | Miss | Branch | BrPart | Cover |
|---|---|---|---|---|---|
| ci_audit/analyze.py | 159 | 11 | 66 | 13 | 89% |
| ci_audit/collect.py | 138 | 4 | 38 | 2 | 97% |
| ci_audit/report.py | 54 | 3 | 10 | 5 | 88% |
| **TOTAL** (`__init__.py` fully covered) | 355 | 18 | 114 | 20 | **92%** |

## Full suite with coverage

Command (same flags as the `ci.yml` "Tests with coverage" step, plus reporting flags):

```bash
python -m pytest --cov=ci_failure_orchestrator --cov-report=term-missing \
  --cov-report=xml:<out>/coverage.xml -rfEsxX -p no:cacheprovider --durations=15
```

### Run 1: `.venv/bin/python -m pytest ...` (venv not on `PATH`, `GITHUB_TOKEN` present in the ambient environment)

`3 failed, 816 passed, 1 warning in 43.92s`, exit 1 ([log](2026-10-11-evidence/full-suite-run1-python-not-on-path.log)).

| Failed test | Assertion |
|---|---|
| `tests/test_patch_sandbox.py::test_patch_verification_isolated_from_source_checkout` | `assert result.passed is True` → `assert False is True` |
| `tests/test_patch_sandbox.py::test_verification_stops_on_first_failure` | `assert result.steps[0].returncode == 2` → `assert 127 == 2` |
| `tests/test_repair_execution.py::test_pipeline_verifies_patch_and_preserves_source` | `assert evaluation.passed is True` → `AssertionError` |

**Cause (environmental, verified):** these tests run verification commands as a bare `("python", "-c", ...)`. The audit machine only has `python3`; `which python` returned nothing, and return code 127 is "command not found". In GitHub Actions `setup-python` puts `python` on `PATH`, so CI is not affected. This is a portability assumption in the tests, not evidence of a product bug; it is reported here and not changed.

### Run 2: venv first on `PATH`, `GITHUB_TOKEN`/`GH_TOKEN` unset

```bash
env -u GITHUB_TOKEN -u GH_TOKEN PATH="$PWD/.venv/bin:$PATH" python -m pytest --cov=... (as above)
```

`819 passed, 1 warning in 41.89s` (wall clock 42.5 s), exit 0 ([log](2026-10-11-evidence/full-suite-run2-venv-on-path.log)). A repeat run without coverage also gave `819 passed, 1 warning in 34.27s` ([log](2026-10-11-evidence/repeat-run-2.log)). No flaky tests seen in these runs (only two clean runs, so this is weak evidence).

Skips: **0**. xfail/xpass: **0**. Errors: **0**.

Warning (both runs): `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.` (from `fastapi/testclient.py`).

Slowest tests: `test_demo_scenarios.py::...[timeout]` (≈5.2 s), `test_demo_repo.py::test_demo_repo_goes_from_red_ci_to_verified_local_repair_with_evidence` (≈3.3 s), `test_server_worker.py::test_heartbeat_keeps_long_run_from_being_recovered` (≈2.1 s). Full list in the logs.

### Coverage (run 2)

`TOTAL 14491 stmts, 1587 miss, 3410 branches, 601 partial → 86%` (37 files 100% covered). From `coverage.xml`: line rate 89.05% (12,904 / 14,491 lines), branch rate 73.7%. Run 1 gave the same 86% (1,583 missed statements; the small difference comes from the 3 failing tests taking different paths).

Per package (from `coverage.xml`):

| Package | Line | Branch |
|---|---|---|
| `ci_failure_orchestrator` (top-level modules) | 87.1% | 67.0% |
| `ci_audit` | 94.9% | 82.5% |
| `doctor` | 95.9% | 82.8% |
| `foundation` | 92.3% | 83.2% |
| `foundation.benchmark` | 80.0% | 55.7% |
| `foundation.observability` | 83.6% | 60.8% |
| `governed` | 89.2% | 65.3% |
| `server` | 87.5% | 69.0% |
| `service` | 93.5% | 82.5% |

Lowest-covered modules (combined %, stmts):

| Module | Cover | Stmts |
|---|---|---|
| `ablation.py` | 0% | 23 |
| `benchmark.py` | 0% | 28 |
| `doctor/__main__.py` | 0% | 2 |
| `foundation/observability/recovery_metrics.py` | 0% | 13 |
| `openai_merge_resolver.py` | 0% | 28 |
| `foundation/observability/__init__.py` | 9% | 29 |
| `governed/explain.py` | 17% | 22 |
| `foundation/benchmark/injection.py` | 32% | 56 |
| `server/settings.py` | 40% | 53 |
| `provenance.py` | 53% | 39 |
| `cli.py` | 60% | 475 |
| `config.py` | 60% | 10 |

The full per-file `term-missing` table is in [`full-suite-run2-venv-on-path.log`](2026-10-11-evidence/full-suite-run2-venv-on-path.log). `coverage.xml` (≈640 KB) was not committed; it is regenerated by `reproduce-audit.sh`.

## Other `ci.yml` "test" job steps (extra check)

All pass locally ([`ci-static-checks.log`](2026-10-11-evidence/ci-static-checks.log)): trust control-plane `ruff check` (exit 0), canonical docstrings `ruff --select D101,D102,D103,D106,D417,D419` (exit 0), `mypy --follow-imports=skip` on 6 files ("Success: no issues found in 6 source files"), trust integration tests (23 passed), `ci-orchestrator rank` smoke test (exit 0).

## Public-repository audit (read-only)

- **Target:** `Kozphy/ci-failure-orchestrator` (public), last 30 days, capped at 30 runs / 5 logs.
- **Auth:** none. `GITHUB_TOKEN`/`GH_TOKEN` were explicitly unset; the tool reported `"authenticated": false`.
- **Safety:** `ci-audit-collect` only lists runs, lists jobs and requests job logs (HTTP GET). The only POST in `github_client.py` is `rerun`, which `ci_audit/` never calls. No reruns, comments, issues, PRs, labels or dispatches were made.

```bash
env -u GITHUB_TOKEN -u GH_TOKEN ci-orchestrator ci-audit-collect --repo Kozphy/ci-failure-orchestrator \
  --days 30 --max-runs 30 --max-logs 5 --output public-audit-export.json
ci-orchestrator ci-audit-report public-audit-export.json --output public-audit-report.md --json public-audit-analysis.json
```

Collect output (exit 0, ≈68 s):

```json
{
  "outcome": "COLLECTED",
  "output": "public-audit-export.json",
  "runs": 30,
  "jobs": 40,
  "failed_jobs": 2,
  "warnings": 1,
  "authenticated": false
}
```

Report output (exit 0):

```json
{
  "outcome": "REPORTED",
  "output": "public-audit-report.md",
  "findings": [
    "F-DUP Medium: push and pull_request both run on the same commits (7% of minutes)"
  ]
}
```

Main results ([full generated report](2026-10-11-evidence/public-audit-report.md)):

- 30 decided runs, 2 failed (7%), 0 reruns, ≈45 runner-minutes, ≈3 minutes of duplicate push + pull_request runs (finding **F-DUP**, Medium).
- Both failures are workflow `ci`, job `server-image`:
  - run `37332637994`, push, `head_sha` **`f7b6cf2e65b3d2ef3f15cecb4fc1c65874c3f56f` (the audited revision)**, 2026-10-05 15:24 UTC (23:24 Taipei);
  - run `37330654005`, pull_request, `head_sha` `8f6c8188…`, 2026-10-05 15:10 UTC.
  - The `test` and `server-postgres` jobs in both runs **passed**.
- Classification is `unknown` and the recorded step is `Compose logs` (an `if: always()` step), because the failed-job logs could not be downloaded: `GitHub API returned HTTP 403: {"message":"Must have admin rights to Repository." ...}`. The real root cause of the `server-image` failure is **not determined** by this audit.

The raw export (`public-audit-export.json`, ≈37 KB of run metadata) was not committed; the generated analysis JSON and report are.

## Failures, gaps and limitations

1. **Upstream CI is red at the audited SHA.** The `ci` workflow's `server-image` job (Docker Compose smoke test against PostgreSQL + API + worker) failed for `f7b6cf2`. It was **not reproduced locally** (no Docker on the audit machine), and its logs need admin rights, so the cause is unknown.
2. **PostgreSQL contract tests not run.** `tests/test_durable_store_contract.py` only adds the `postgres` backend when `TEST_DATABASE_URL` is set. It was unset, so only the `file` and `sqlite` backends ran. These are left out at collection time, so they **do not show as skips**; the "0 skipped" count does not mean PostgreSQL was covered.
3. **Tests assume a `python` executable.** 3 tests fail with exit 127 where only `python3` exists (run 1). They pass with the venv on `PATH`.
4. **No lockfile.** Dependencies resolve to the newest versions allowed by the lower bounds, so results may differ on another day. The exact versions used are in `pip-freeze.txt`.
5. **Public audit limits:** unauthenticated (60 requests/hour), capped at 30 runs (`runs_truncated: true`; all 30 runs fall on 2026-10-05, so the "30-day" window is really ~1.5 hours of activity), job logs unavailable without admin rights, and minute figures are estimates.
6. **Flakiness evidence is thin:** two clean full runs in a row with the venv on `PATH`; no repeated focused stress runs.
7. **Not run:** other workflows' scripts (benchmarks, production-proof scripts, self-heal, promotion), `docker compose` smoke, Codecov upload, and anything that needs secrets or write access.
8. `ruff`/`mypy` versions are newer than whatever CI last used (unpinned). They passed here, but this is not a guarantee for CI.

## Files in this change

- `docs/audit/2026-10-11-audit-report.md`: this report
- `docs/audit/reproduce-audit.sh`: reruns the commands above (existing tests and read-only commands only)
- `docs/audit/2026-10-11-evidence/`: raw logs (`focused-ci-audit.log`, `full-suite-run1-python-not-on-path.log`, `full-suite-run2-venv-on-path.log`, `repeat-run-2.log`, `ci-static-checks.log`, `public-audit-collect.log`, `public-audit-report.log`), `public-audit-report.md`, `public-audit-analysis.json`, `pip-freeze.txt`

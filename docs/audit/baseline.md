# Baseline inventory

Date observed: 2026-11-06. Default branch `main` at `f3b87fb6ced3c8851ed8b14e23ed89d700eef208`. Local pytest was not run on that commit in this session. GitHub Actions results below are from `gh`, not from a re-execution.

## Environment

| Item | Observed |
| --- | --- |
| Language | Python, `requires-python >= 3.10` |
| Package version | `pyproject.toml` `1.2.0`. `ci_failure_orchestrator/__init__.py` `__version__` is `1.0.0`. |
| Runtime dependency | `PyYAML>=6.0` |
| Test runner | pytest. Dev extra also installs pytest-cov, ruff, mypy, httpx. |
| Optional extras | `openai`, `observability`, `server` (FastAPI, uvicorn, SQLAlchemy, pydantic, psycopg) |
| CLIs | `ci-orchestrator`, `actions-doctor` |
| CI | GitHub Actions. `ci.yml` permissions are `contents: read`. |
| License | MIT |
| Operating system of this inspection | Windows. Hosted CI jobs below ran on GitHub-hosted runners. |

## Hosted CI on the baseline SHA

Workflow `ci` run [42134187842](https://github.com/Kozphy/ci-failure-orchestrator/actions/runs/42134187842), push to `main`, conclusion `success`.

| Job | Conclusion |
| --- | --- |
| test | success |
| server-image | success |
| server-postgres | success |

Coverage percentage was not read from the log. A green job is not a coverage or safety proof.

`CI Doctor` runs on that SHA in the same window were `skipped` (workflow_run filter). That is not a diagnosis of a failed build.

## Claim classification

| Claim | Class | Why |
| --- | --- | --- |
| Read-only CI Doctor Action for a run id and a saved log | VERIFIED in tree | `action.yml`, `doctor/action.py`. Hosted run of the saved-log workflow was not observed. |
| Deterministic classifier and secret redaction | PARTIAL | Code and unit tests exist. Redaction is a pattern list. Accuracy on external logs was not measured here. |
| Repair loop, policy, sandbox | PARTIAL | Implemented and covered by tests in the repo. Not re-run locally on this SHA in this session. Hosted `ci` test job succeeded. |
| Auto-merge | PLANNED off | `auto-merge-after-checks.yml` is `workflow_dispatch` and the job `if` is false. The file still requests write permission. |
| Self-heal and agent issue delivery | PLANNED off | `workflow_dispatch` only. Jobs require event payloads a dispatch does not provide. Write permissions remain in the file. |
| US$149 audit as a sold service | UNVERIFIED | Offer text exists. No paid order is recorded. |
| Enterprise certification, production users, ROI | UNVERIFIED | Not present as evidence. |
| v1.0 release candidate | PLANNED | Package versions disagree. Release gate in `release-gate.md` is BLOCKED. |

## Existing issues

Open issues at inspection: #21 (AI-native maturity), #7, #6, #5 (CI repair). None use the AUD/SEC/QA/CICD/PERF/REL ids. Those ids are specified in `backlog.md`. GitHub issues for them were not opened in this change.

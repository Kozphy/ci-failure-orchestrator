# Repository audit

Date: 2026-11-05. Machine: Windows, Python 3.14. Branch created from `origin/main`. This file records what was inspected and what was run. It does not replace older audits.

## Commands

| Command | Result |
| --- | --- |
| `python -m pytest -q tests/test_doctor_action.py` | 11 passed, before the wording fix. 11 passed again after it, in a 12-test combined run. |
| `python -m pytest -q --tb=no` | Exit 1. The progress log showed one `F`. The summary named `tests/test_security_boundaries.py::test_canonical_code_never_calls_a_merge_api`. |
| Re-run of that test plus `tests/test_doctor_action.py` | 12 passed after the report string no longer contained a bare "merge". |
| GitHub Actions for this change | NOT TESTED. No hosted run was observed. |

The full suite was not started a second time. Environment: repository checkout, `PYTHONIOENCODING=utf-8`, no `GITHUB_TOKEN` required for the saved-log tests.

## Matrix

| Capability | Code evidence | Test evidence | Status | Gap | Priority |
| --- | --- | --- | --- | --- | --- |
| CI failure diagnosis | `doctor/diagnose.py` `diagnose_log` and `diagnose_run`. Action entry `doctor/action.py`. | Saved-log test does not call the API reader. Existing run-id tests still pass. | VERIFIED | Hosted Action run of the new inputs is NOT TESTED. | P0 |
| Failure classification | `ci_audit/collect.py` classifier used by the doctor. | Fixture log classed `test_failure`. Hostile log classed `unknown`. | PARTIALLY VERIFIED | One fixture is not an accuracy rate. | P1 |
| Repair recommendations | `next_step` and `verification` on the diagnosis. Report field `validation_status` is `not_executed`. | Report text contains `not_executed`. | VERIFIED | The Action does not apply a fix. That is intentional. | P2 |
| GitHub Action | `action.yml` composite. Run-id mode already existed. Saved-log inputs added. | Static test: no `${{` inside `run:` scripts. Workflow permissions test. | PARTIALLY VERIFIED | `setup-python` is pinned to tag `v7`, not a commit SHA. No hosted execution of this commit. | P0 |
| CLI | `actions-doctor` and `ci-orchestrator` in `pyproject.toml`. | Not re-run as a process in this session. Action tests call `doctor.action.main`. | PARTIALLY VERIFIED | CLI process smoke was not repeated. | P2 |
| JSON output | `diagnosis.json` plus the report builder. | Saved-log test reads `source == log`. | VERIFIED | Schema is the doctor diagnosis dict, not a new public JSON Schema file. | P1 |
| Markdown reports | `doctor/reliability_report.py`. | Saved-log test reads the Markdown file. Sample checked in from the fixture. | VERIFIED | Sample is a fixture, not a 30-day audit. | P1 |
| Secret redaction | `foundation/sanitization.py` via `clean_untrusted`. `redact-secrets=false` is rejected. | Hostile log token absent from stdout in the older test and from the report in the new test. | PARTIALLY VERIFIED | Redaction is a pattern list, not a proof. | P0 |
| Policy gates | `policy_preview` outcome `ESCALATE` or `ELIGIBLE`. Exit 4 when `fail-on-policy-violation` is true. | Hostile log returns exit 4. | VERIFIED | Exit 4 does not block a merge elsewhere. The Action never merges. | P1 |
| Multi-repo support | Run-id mode takes `owner/name` for one repository. | Malformed repository strings are rejected. | PARTIALLY VERIFIED | No fleet or org scan. | P3 |
| Real-world validation | Older changelog text describes a past local install against run 35718565691. | That run was not repeated in this session. | DOCUMENTATION ONLY | Do not treat the changelog sentence as a new observation. | P1 |
| Customer onboarding | `business/` templates. | None. | MISSING | No intake has been filled. Zero paid orders. | P1 |

## Assumptions

- `origin/main` at the branch point already contained the run-id Action. That was confirmed by reading `action.yml` before editing it.
- EvalForge was not part of this change.
- A full second pytest run would likely pass after the one-line string edit, because the first run's only reported failure was that detector. That is an inference. It is not a second execution.

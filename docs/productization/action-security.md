# Action security

| Control | Where |
| --- | --- |
| Read-only defaults | `ci-doctor.yml` permissions are `actions: read` and `contents: read`. The saved-log example is `contents: read` and `workflow_dispatch` only. |
| No `pull_request_target` | Neither workflow uses it. Fork code is not checked out. |
| No shell interpolation of inputs | Inputs are environment variables. `tests/test_doctor_action.py` asserts `${{` is absent from `run:` scripts. |
| Untrusted logs | `clean_untrusted` neutralizes `::` workflow commands and redacts known secret patterns before the report is written. |
| Commands in the log are not run | The step calls `python -m ci_failure_orchestrator.doctor.action` only. |
| No auto-merge and no push | This action has no write permission and no `git push`. |
| Token handling | `github-token` is an env var for the API client. The error path redacts token-shaped strings. Saved-log mode does not read the token. |
| Path and size | The log must be a file of at most 2 MB. Newlines in the path are rejected. The report parent directory must already exist. |
| Time bound | The diagnose step sets `timeout-minutes: 5`. |
| Redaction switch | `redact-secrets: false` is rejected. |
| External upload | The action does not post logs to another service. |

Residual risk: the redactor is a pattern list. A workflow author can still point `log-path` at any file on the runner. `actions/setup-python@v7` and `actions/checkout@v7` are not pinned to commit SHAs. A job summary can still contain classified log lines, so do not put secrets in the log in the first place.

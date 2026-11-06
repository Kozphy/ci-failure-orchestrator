# Install the CI Doctor Action

The composite action is `action.yml` at the repository root. It already existed for a GitHub run id. Saved-log mode does not call the GitHub API.

## Saved log

```yaml
permissions:
  contents: read

jobs:
  diagnose:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: Kozphy/ci-failure-orchestrator@<commit-sha>
        with:
          log-path: path/to/job.log
          output-format: both
          redact-secrets: "true"
```

Pin `<commit-sha>` to a commit you have read. There is no git tag for this action in the repository today. `uses: ./` works after `actions/checkout` of this repo. A marketplace release does not exist.

`redact-secrets: "false"` fails the step. `fail-on-policy-violation: "true"` exits 4 when the preview is `ESCALATE`. That does not merge or push.

Outputs: `diagnosis-status`, `failure-category`, `report-path`, `policy-status`, plus the existing `failure-class` and `diagnosis-file`.

## One failed run

`.github/workflows/ci-doctor.yml` listens for a failed `ci` workflow in this repository. Permissions are `actions: read` and `contents: read`. The checkout step does not set `ref`, so it checks out the default branch, not the failed head and not a fork head.

Pass `run-id` for a manual dispatch. The token input defaults to `github.token`.

## Local reproduction

```bash
pip install -e .
python -c "import sys; from ci_failure_orchestrator.doctor.action import main; sys.exit(main({'CI_DOCTOR_LOG_PATH':'examples/ci-doctor/pytest-failure.txt','RUNNER_TEMP':'.'}))"
```

On Windows, prefer a temporary `RUNNER_TEMP` so the command does not write `ci-doctor/` into the work tree. The fixture log is not a downloaded GitHub job.

## Uninstall

Remove the workflow file that references the action. Revoke any fine-grained token you created. No GitHub App is installed by this action.

## Not supported

Live log download without `actions:read`, `pull_request_target`, auto-merge, applying a patch, an LLM key, more than one log per step, and logs over 2 MB. Third-party actions in `action.yml` are still pinned to major tags (`actions/setup-python@v7`), not to commit SHAs.

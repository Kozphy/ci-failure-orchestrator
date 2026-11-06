# Implementation backlog

GitHub issues #5, #6, #7, and #21 were open on 2026-11-06. None use these ids, so they were not reused. Creating the fourteen GitHub issues was not completed in the same step as this file. If they are opened later, do not file a second copy.

| ID | Acceptance | Tests | Evidence | Depends on |
| --- | --- | --- | --- | --- |
| AUD-01 | Baseline SHA, toolchain, and hosted CI URL are written down. Claims classified. | Inspection only | `baseline.md` | none |
| SEC-01 | Threat model rows cite a file, a test, or an absence. Not called a pen test. | Re-run doctor and security-boundary tests on the release SHA | `threat-model.md` | AUD-01 |
| SEC-02 | Diagnosis workflows stay read-scoped. Dormant write workflows are removed or cannot write without a new review. No `pull_request_target`. | Static permission test | workflow diff | SEC-01 |
| SEC-03 | The Action does not run commands from a log. Cross-repo use is tested or documented as unsupported. | Adversarial log test and one negative cross-repo test | test output and SHA | SEC-01 |
| QA-01 | Full pytest on the release SHA exits 0, or the failure is named. Coverage is recorded and not treated as safety. | `python -m pytest -q` with coverage | log and SHA | AUD-01 |
| QA-02 | Labeled fixtures report accuracy with a denominator. One fixture is not an accuracy rate. | Existing benchmark script | result JSON | QA-01 |
| CICD-01 | Required checks are listed from GitHub, or the permission gap is stated. A skipped CI Doctor run is not a pass. | `gh run view` | run URL | AUD-01 |
| AUD-02 | Stored audit-event fields are listed from code. One redacted sample is attached. | Existing audit-store test | redacted JSON | QA-01 |
| AUD-03 | Every control row points at a test or an open issue. High rows are not closed without a run on the release SHA. | The tests named in the matrix | updated matrix | SEC-01, QA-01 |
| PERF-01 | Offline benchmark is re-run. Synthetic data is labeled. No savings figure. | Offline benchmark script | evidence file and exit code | QA-01 |
| REL-01 | Rollback is rehearsed on a non-default branch without force-push. | `git revert` on a scratch branch | transcript | CICD-01 |
| REL-02 | Diagnosis Actions are pinned to SHAs, or the release stays blocked. Versions match before any 1.0.0 tag. No tag in this item. | Pin check | diff | SEC-02 |
| AUD-04 | A reviewer who did not write the change records pass or fail against the release gate and names the SHA. | Whatever that reviewer re-runs | review record | AUD-03, SEC-01 |
| REL-03 | The release gate is updated only from new evidence. Any BLOCKED row keeps the release BLOCKED. No tag until every mandatory row is PASS. | The open items above | `release-gate.md` | AUD-04, REL-01, REL-02, PERF-01, QA-02 |

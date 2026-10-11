# GitHub CI Reliability Audit: `Kozphy/ci-failure-orchestrator`

Window: 2026-09-11 to 2026-10-11 (30 days) · 30 completed runs (30 passed or failed, the rest skipped or cancelled) · 2 failed jobs

## 1. Executive summary

- **Failure rate:** 7% of decided runs failed (2 of 30).
- **Rerun rate:** 0% of runs were rerun; 0 commits failed and then passed with no code change.
- **Estimated waste:** 3 of 45 minutes (7%) went to duplicate runs, superseded attempts and cancelled jobs, about **3 minutes/month**.
- **Estimated usage:** about 45 minutes/month at the current rate.

**Fix first:** push and pull_request both run on the same commits (7% of minutes). Limit push triggers to protected branches so PR branches build once via pull_request.

> _Reviewer: confirm or edit this section before delivery._

## 2. Repository and workflow inventory

| Workflow | Runs | Failure rate | Reruns | p50 min | p90 min | Queue p50 | Minutes | Share |
|---|---|---|---|---|---|---|---|---|
| ci | 2 | 100% | 0 | 1.6 | 2.4 | 0.0 | 8 | 18% |
| CI Doctor | 5 | 0% | 0 | 0.4 | 0.4 | 0.0 | 5 | 11% |
| Production Proof | 2 | 0% | 0 | 1.2 | 1.6 | 0.0 | 4 | 9% |
| dependabot-updates (dynamic) | 2 | 0% | 0 | 1.1 | 1.9 | 0.0 | 4 | 9% |
| repair-execution | 2 | 0% | 0 | 1.2 | 1.8 | 0.0 | 4 | 9% |
| security | 2 | 0% | 0 | 1.1 | 1.5 | 0.0 | 4 | 9% |
| promotion | 2 | 0% | 0 | 1.3 | 1.6 | 0.0 | 3 | 7% |
| provider-contract | 3 | 0% | 0 | 0.8 | 0.9 | 0.0 | 3 | 7% |
| ct | 2 | 0% | 0 | 1.1 | 1.5 | 0.0 | 2 | 4% |
| foundation-benchmark | 2 | 0% | 0 | 0.5 | 1.1 | 0.0 | 2 | 4% |
| patch-sandbox | 2 | 0% | 0 | 0.4 | 0.9 | 0.0 | 2 | 4% |
| repair-benchmark | 2 | 0% | 0 | 0.5 | 1.0 | 0.0 | 2 | 4% |
| research-evidence | 2 | 0% | 0 | 0.7 | 1.2 | 0.0 | 2 | 4% |

Minutes by runner OS: linux 45

## 3. Failure taxonomy

| Category | Failed jobs | Share | Example |
|---|---|---|---|
| unknown | 2 | 100% | [server-image failed](https://github.com/Kozphy/ci-failure-orchestrator/actions/runs/37332637994/job/111839326078) |

Top failing jobs:

| Workflow | Job | Failures | Share | Example |
|---|---|---|---|---|
| ci | server-image | 2 | 100% | [run](https://github.com/Kozphy/ci-failure-orchestrator/actions/runs/37332637994/job/111839326078) |

## 4. CI bottlenecks

Slowest jobs (minutes, rounded up per job):

| Workflow | Job | Runs | p50 | p90 |
|---|---|---|---|---|
| dependabot-updates (dynamic) | Dependabot | 2 | 2.0 | 2.0 |
| ci | test | 2 | 2.0 | 2.0 |
| promotion | canary | 1 | 2.0 | 2.0 |
| Production Proof | test-and-gate | 2 | 2.0 | 2.0 |
| repair-execution | repair-execution | 2 | 2.0 | 2.0 |
| CI Doctor | diagnose | 5 | 1.0 | 1.0 |
| patch-sandbox | verify | 2 | 1.0 | 1.0 |
| provider-contract | provider-contract | 3 | 1.0 | 1.0 |
| repair-benchmark | benchmark | 2 | 1.0 | 1.0 |
| ct | continuous-testing | 2 | 1.0 | 1.0 |

## 5. Flaky-test indicators

Commits where a workflow failed and then passed without a code change. These are indicators, not proof.

_None found in this window._

## 6. Retry analysis

- Runs with more than one attempt: 0 (0%).
- Minutes spent on superseded attempts: 0.
- Reruns that turned red into green: 0.

## 7. Cost and runtime waste

Public repository: GitHub-hosted minutes are free, so minute figures measure runner time and feedback delay, not spend.

| Source | Minutes in window | Per month (est.) |
|---|---|---|
| Duplicate push + pull_request runs | 3 | 3 |
| Superseded attempts (reruns) | 0 | 0 |
| Cancelled jobs | 0 | 0 |
| **Total waste** | 3 | 3 |
| Failed jobs (not counted as waste) | 2 | 2 |

## 8. Risk ranking

| ID | Severity | Finding | Effort | Minutes/month at stake |
|---|---|---|---|---|
| F-DUP | Medium | push and pull_request both run on the same commits (7% of minutes) | Low | 3 |

## 9. Evidence

- **F-DUP:** 3 duplicate runs, 3 billed minutes.

Most frequent failing steps:

| Workflow | Job | Step | Failures |
|---|---|---|---|
| ci | server-image | Compose logs | 2 |

## 10. Recommended fixes

1. **push and pull_request both run on the same commits (7% of minutes)** (Medium, effort Low): Limit push triggers to protected branches so PR branches build once via pull_request.

> _Reviewer: confirm or edit this section before delivery._

## 11. Quick wins

- Limit push triggers to protected branches so PR branches build once via pull_request.

## 12. 30-day roadmap

- **Week 1:** apply the quick wins above.
- **Week 2:** fix the top finding (F-DUP) and its failing job.
- **Week 3:** fix the next finding and add a failure-rate check to the weekly review.
- **Week 4:** re-run this audit over the same window length and compare.

> _Reviewer: confirm or edit this section before delivery._

## 13. Method and limitations

- Data: GitHub Actions REST API, read-only. No code, secrets or full logs are stored; failure messages are one scrubbed line.
- Minutes are estimates from job start/end times rounded up per job, not billing data. Larger runners bill differently.
- Failure categories come from a regex classifier and are not calibrated; spot-check them before acting.
- Flaky signals are indicators: a commit that failed then passed may also reflect external outages.
- Run list capped at 30 runs; older runs in the window were not analyzed.
- 2 failed jobs were classified from job and step names only (log not fetched).
- Collection warning: 2 failed-job logs could not be downloaded; first error: GitHub API returned HTTP 403: {"message":"Must have admin rights to Repository.","documentation_url":"https://docs.github.com/rest/actions/workflow-jobs#download-job-logs-for-a-workflow-run","status":

# GitHub CI Reliability Audit: `Kozphy/ci-failure-orchestrator`

Window: 2026-09-03 to 2026-10-03 (30 days) · 359 completed runs (261 passed or failed, the rest skipped or cancelled) · 10 failed jobs

## 1. Executive summary

- **Failure rate:** 4% of decided runs failed (10 of 261).
- **Rerun rate:** 0% of runs were rerun; 0 commits failed and then passed with no code change.
- **Estimated waste:** 32 of 297 minutes (11%) went to duplicate runs, superseded attempts and cancelled jobs, about **32 minutes/month**.
- **Estimated usage:** about 297 minutes/month at the current rate.

**Fix first:** push and pull_request both run on the same commits (11% of minutes). Limit push triggers to protected branches so PR branches build once via pull_request.

> _Reviewer: confirm or edit this section before delivery._

## 2. Repository and workflow inventory

| Workflow | Runs | Failure rate | Reruns | p50 min | p90 min | Queue p50 | Minutes | Share |
|---|---|---|---|---|---|---|---|---|
| security | 23 | 13% | 0 | 1.0 | 1.7 | 0.0 | 52 | 18% |
| ci | 29 | 3% | 0 | 0.6 | 1.3 | 0.0 | 30 | 10% |
| provider-contract | 29 | 0% | 0 | 0.3 | 0.9 | 0.0 | 29 | 10% |
| repair-execution | 29 | 0% | 0 | 0.4 | 0.9 | 0.0 | 29 | 10% |
| Production Proof | 21 | 0% | 0 | 0.5 | 0.8 | 0.0 | 21 | 7% |
| ct | 21 | 0% | 0 | 0.4 | 1.0 | 0.0 | 21 | 7% |
| patch-sandbox | 21 | 0% | 0 | 0.3 | 1.0 | 0.0 | 21 | 7% |
| promotion | 21 | 0% | 0 | 0.5 | 0.9 | 0.0 | 21 | 7% |
| repair-benchmark | 21 | 0% | 0 | 0.3 | 0.6 | 0.0 | 21 | 7% |
| dependabot-updates (dynamic) | 10 | 0% | 0 | 0.9 | 1.9 | 0.0 | 15 | 5% |
| foundation-benchmark | 12 | 0% | 0 | 0.3 | 0.5 | 0.0 | 12 | 4% |
| research-evidence | 12 | 0% | 0 | 0.4 | 1.1 | 0.0 | 12 | 4% |
| Auto merge after checks | 6 | 100% | 0 | 1.0 | 1.2 | 0.0 | 6 | 2% |
| update-graph (dynamic) | 3 | 0% | 0 | 1.0 | 1.4 | 0.0 | 4 | 1% |
| self-heal | 101 | 0% | 0 | 0.0 | 0.2 | 0.0 | 3 | 1% |

Minutes by runner OS: linux 297

## 3. Failure taxonomy

| Category | Failed jobs | Share | Example |
|---|---|---|---|
| unknown | 6 | 60% | [jq: error: Could not open file : No such file or directory](https://github.com/Kozphy/ci-failure-orchestrator/actions/runs/34814719507/job/103882912963) |
| security_scan_failure | 3 | 30% | [🛑 Leaks detected, see job summary for details](https://github.com/Kozphy/ci-failure-orchestrator/actions/runs/36405950411/job/108874598707) |
| lint_failure | 1 | 10% | [Found 1 error.](https://github.com/Kozphy/ci-failure-orchestrator/actions/runs/35718565691/job/106715777966) |

Top failing jobs:

| Workflow | Job | Failures | Share | Example |
|---|---|---|---|---|
| Auto merge after checks | Auto merge gate | 6 | 60% | [run](https://github.com/Kozphy/ci-failure-orchestrator/actions/runs/34814719507/job/103882912963) |
| security | Gitleaks | 3 | 30% | [run](https://github.com/Kozphy/ci-failure-orchestrator/actions/runs/36405950411/job/108874598707) |
| ci | test | 1 | 10% | [run](https://github.com/Kozphy/ci-failure-orchestrator/actions/runs/35718565691/job/106715777966) |

## 4. CI bottlenecks

Slowest jobs (minutes, rounded up per job):

| Workflow | Job | Runs | p50 | p90 |
|---|---|---|---|---|
| foundation-benchmark | foundation-benchmark | 12 | 1.0 | 1.0 |
| patch-sandbox | verify | 21 | 1.0 | 1.0 |
| ct | continuous-testing | 21 | 1.0 | 1.0 |
| Production Proof | test-and-gate | 21 | 1.0 | 1.0 |
| repair-execution | repair-execution | 29 | 1.0 | 1.0 |
| promotion | canary | 13 | 1.0 | 1.0 |
| ci | test | 29 | 1.0 | 1.0 |
| security | CodeQL | 23 | 1.0 | 2.0 |
| security | Gitleaks | 23 | 1.0 | 1.0 |
| repair-benchmark | benchmark | 21 | 1.0 | 1.0 |

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
| Duplicate push + pull_request runs | 32 | 32 |
| Superseded attempts (reruns) | 0 | 0 |
| Cancelled jobs | 0 | 0 |
| **Total waste** | 32 | 32 |
| Failed jobs (not counted as waste) | 10 | 10 |

## 8. Risk ranking

| ID | Severity | Finding | Effort | Minutes/month at stake |
|---|---|---|---|---|
| F-DUP | Medium | push and pull_request both run on the same commits (11% of minutes) | Low | 32 |
| F-TOPJOB | Medium | One job causes 60% of failed jobs: Auto merge after checks / Auto merge gate | Medium | - |
| F-SIGNAL | Low | 60% of failures match no known failure category | Low | - |

## 9. Evidence

- **F-DUP:** 32 duplicate runs, 32 billed minutes.
- **F-TOPJOB:** 6 failures; example https://github.com/Kozphy/ci-failure-orchestrator/actions/runs/34814719507/job/103882912963
- **F-SIGNAL:** 6 of 10 downloaded failure logs matched no known error pattern.

Most frequent failing steps:

| Workflow | Job | Step | Failures |
|---|---|---|---|
| Auto merge after checks | Auto merge gate | Resolve pull request and merge only when every check is green | 6 |
| security | Gitleaks | Run gitleaks/gitleaks-action@v3 | 3 |
| ci | test | Trust control-plane lint | 1 |

## 10. Recommended fixes

1. **push and pull_request both run on the same commits (11% of minutes)** (Medium, effort Low): Limit push triggers to protected branches so PR branches build once via pull_request.
2. **One job causes 60% of failed jobs: Auto merge after checks / Auto merge gate** (Medium, effort Medium): Make this job the first fix target: read its failure category and failing step in the evidence section.
3. **60% of failures match no known failure category** (Low, effort Low): Read the uncategorized examples in section 3 by hand; where the error line is vague, make the step print one explicit error (pytest -rA summaries, set -e, a clear message before exit).

> _Reviewer: confirm or edit this section before delivery._

## 11. Quick wins

- Limit push triggers to protected branches so PR branches build once via pull_request.
- Read the uncategorized examples in section 3 by hand; where the error line is vague, make the step print one explicit error (pytest -rA summaries, set -e, a clear message before exit).

## 12. 30-day roadmap

- **Week 1:** apply the quick wins above.
- **Week 2:** fix the top finding (F-DUP) and its failing job.
- **Week 3:** fix the next finding (F-TOPJOB) and add a failure-rate check to the weekly review.
- **Week 4:** re-run this audit over the same window length and compare.

> _Reviewer: confirm or edit this section before delivery._

## 13. Method and limitations

- Data: GitHub Actions REST API, read-only. No code, secrets or full logs are stored; failure messages are one scrubbed line.
- Minutes are estimates from job start/end times rounded up per job, not billing data. Larger runners bill differently.
- Failure categories come from a regex classifier and are not calibrated; spot-check them before acting.
- Flaky signals are indicators: a commit that failed then passed may also reflect external outages.

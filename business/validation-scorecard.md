# Validation scorecard

Measured values below come from one local session unless a row says otherwise. Business rows are empty on purpose.

## Engineering

| Metric | Formula | Target | Measured | Status |
| --- | --- | --- | --- | --- |
| Doctor action tests | passed / collected in `tests/test_doctor_action.py` | all passed | 11 / 11 on 2026-11-05, Python 3.14, Windows | PASS |
| Full suite | passed / collected for `python -m pytest -q` | no new failures | 2026-11-05 run exited 1. One failure: a report string contained the word the merge detector forbids. After that string changed, the detector test passed. The full suite was not re-run. | FAIL then fixed locally |
| Saved-log diagnosis | fixture runs with `diagnosis-status=diagnosed` / fixture runs | 1 / 1 | 1 / 1 local fixture `examples/ci-doctor/pytest-failure.txt` | PASS |
| Classification on that fixture | category equals the assertion failure the log contains | test_failure | test_failure | PASS |
| False-positive rate | wrong category / labeled fixture rows in this change | not enough labels | 1 fixture, so the rate is not estimated | NOT TESTED |
| Report generation | Markdown and JSON written / successful diagnoses in the saved-log test | 1 / 1 | 1 / 1 local | PASS |
| Median execution time | median wall clock of the Action on GitHub | none set | not timed | NOT TESTED |
| Security tests in `test_doctor_action.py` | hostile log, token absent, redact false rejected, no `pull_request_target` | passed | passed in the 11 | PASS |
| GitHub-hosted Action run | observed workflow conclusion | success on a real run | no run observed for this change | NOT TESTED |

## Business

| Metric | Formula | Target | Measured | Status |
| --- | --- | --- | --- | --- |
| Qualified prospects | Experiment A denominator | 10 | 0 | NOT TESTED |
| Outreach responses | positive replies / outreach sent | none set | 0 / 0 | NOT TESTED |
| Trial installations | Experiment B installations | 5 | 0 | NOT TESTED |
| Successful activations | diagnosed / installations | none set | 0 | NOT TESTED |
| Repeat users | second-week users | none set | 0 | NOT TESTED |
| Paid customers | orders with money received | 3 is a v0.3 target, not a current result | 0 | NOT TESTED |
| Revenue | sum of those orders, USD | none | 0 | NOT TESTED |
| Delivery hours per audit | hours / paid audits | none | no audit delivered | NOT TESTED |
| Gross margin | (price - direct cost) / price | none | cost not measured | NOT TESTED |
| Refunds | refunds / paid orders | none | 0 / 0 | NOT TESTED |

## Evidence register

| Metric | Definition | Source | Date | Sample | Limitation | Verification |
| --- | --- | --- | --- | --- | --- | --- |
| Doctor action tests | pytest result for that file | local terminal | 2026-11-05 | 11 tests | one machine | PASS |
| Fixture category | `test_failure` from the checked-in log | `examples/ci-doctor/pytest-failure.txt` | 2026-11-05 | 1 log | simulated log, not a GitHub download | PASS |
| Paid orders | money received | none | 2026-11-05 | 0 | no ledger outside this repo was checked | NOT TESTED |

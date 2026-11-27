# Sample report

This file is the engine output for examples/ci-doctor/pytest-failure.txt. It is a fixture, not a customer audit and not a GitHub-hosted run.

# CI Reliability Audit

Evidence class: single diagnosis. Not a multi-run audit and not a customer engagement.

## 1. Executive summary

Top classification is test_failure.

## 2. Repository and workflow scope

Repository: not provided
Source: log
Run: not a GitHub run

## 3. Evaluation period

Not a time window. This report covers the one log or run that was supplied.

## 4. Evidence sources

log

## 5. Observed CI failures

### F-1

- Severity: medium (policy preview outcome, not a measured incident rate)
- Category: test_failure
- Job: saved-log
- Step: not named
- Evidence: FAILED tests/test_calc.py::test_add - AssertionError: assert 3 == 4
- Evidence line: 4
- Confidence: medium (heuristic)
- Reproduction: pytest -q
- Remediation: Reproduce the failing test with the command below and fix the code or the test it names.
- Validation status: not_executed

## 6. Failure classifications

test_failure

## 7. Frequency and recurrence

Observations in this input: 1. Recurrence was not measured.

## 8. Reliability risks

F-1

## 9. Repair recommendations

- Reproduce the failing test with the command below and fix the code or the test it names.

## 10. Security considerations

- Log text was treated as untrusted data.
- Secret patterns known to the redactor were replaced. This is not a guarantee.
- Recommended commands were not executed.

## 11. Validation results

Policy status: ELIGIBLE.
The recommended remediation was not executed by this report.

## 12. Limitations and unverified assumptions

- One diagnosis is not a 30-day reliability rate.
- No baseline and no post-change measurement are included.
- No business-savings figure is computed.

## 13. Recommended next actions

- A human reviews the finding before any patch or push.

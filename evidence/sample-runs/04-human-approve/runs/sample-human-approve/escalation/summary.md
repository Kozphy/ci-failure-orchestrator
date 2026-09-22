# Human Review Required

## Run

`sample-human-approve`

Escalation ID: `esc-751aa665373f`

Evidence status: `COMPLETE`

## Escalation Reason

- AUTHORIZATION_CHANGE

Escalation reason:
Authorization-related code was modified.

Technical status:
All configured verification checks passed.

Affected files:
- auth/permissions.py

Attempts:
1

Policy result:
ESCALATE

Why review is required:
Authorization-related code was modified.

Remaining uncertainty:
Automated evaluation confirms configured checks but does not prove broader safety properties.

## Original Failure

Original failure:
Failing target:
FAILED tests/test_app.py::test_login - AssertionError
ci/test step=pytest
Classification:
test_failure
Observed error:
AssertionError

## Proposed Repair

Proposed change:
auth change needing human

Files changed:
1
Change categories:
AUTH
Scope:
SMALL
Patch stats:
+1 / -0 lines

### Files

- auth/permissions.py

Patch stats: +1 / -0 lines

## Technical Evaluation

Evaluation:
PASS

Checks:
- PATCH_APPLIED: PASSED
- TARGET_TEST_PASSED: PASSED
- RELEVANT_TESTS_PASSED: UNAVAILABLE
- NO_FORBIDDEN_FILES_CHANGED: PASSED
- NO_NEW_LINT_ERRORS: SKIPPED
- NO_NEW_TYPE_ERRORS: SKIPPED

## Policy Decision

Policy outcome:
ESCALATE

Matched rules:
- POL-009-AUTH-CHANGE

Risk:
HIGH

Reason:
- auth_code_modified

### Matched rules

- POL-009-AUTH-CHANGE

## Retry / Attempt History

Attempts:
1

Attempt 1:
- result: PASS
- proposal_fp: 299cf695ccff
- progress: no
- disposition: RECOVERABLE

## Risk Summary

HIGH

## Unresolved Questions

- Does this authorization change preserve all existing role boundaries?
- Are negative authorization cases sufficiently covered?
- Should check 'RELEVANT_TESTS_PASSED' (UNAVAILABLE) be executed before approval?

## Reviewer Checklist

- [ ] Confirm intended privilege boundaries
- [ ] Review deny paths
- [ ] Review authentication assumptions
- [ ] Review authorization checks
- [ ] Confirm negative tests exist
- [ ] Confirm no privilege broadening outside intended scope

## Evidence References

- proposal: `prop-384f8420759a`
- evaluation: `eval:sample-human-approve`
- policy: `policy:2026-09-22T16:51:23.721125+00:00`
- attempt: `attempt-1`

## Available Reviewer Actions

- APPROVE
- REJECT
- REQUEST_CHANGES
- DEFER

_This package does not recommend a reviewer decision._

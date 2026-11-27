# Risk register and control matrix

Severity here is a review label, not a CVSS score. No scanner was run in this session.

| ID | Risk | Severity | Control | Status |
| --- | --- | --- | --- | --- |
| R1 | Saved log treated as instructions | High | Untrusted-text cleaner and doctor tests | PARTIAL |
| R2 | Secret in a log survives redaction | High | Pattern redactor | PARTIAL |
| R3 | Write-scoped workflows re-enabled | High | Currently dispatch-only or `if: false` | PARTIAL |
| R4 | Actions pinned to moving tags | Medium | `actions/checkout@v7`, `actions/setup-python@v7` | UNVERIFIED as immutable |
| R5 | Two version strings | Low | `1.2.0` vs `__version__` `1.0.0` | VERIFIED mismatch |
| R6 | Claiming a failure-rate improvement | High | Report builder refuses a before/after figure | VERIFIED in the report code |
| R7 | Shared multi-tenant deployment | High | No tenant control | PLANNED absent |
| R8 | Paid pilot delivered without scope | Medium | `business/service-offer.md` | UNVERIFIED commercially |

## Control mapping

| Control objective | Implementation | Test | Gap |
| --- | --- | --- | --- |
| Least privilege for diagnosis | `ci.yml` and `ci-doctor.yml` are read scoped | Workflow static tests | Write workflows still exist for other jobs |
| Isolation of log text | Doctor report quotes the classified line and marks remediation not executed | `test_doctor_action.py` | Not re-run locally on the baseline SHA |
| Authorization denial | Mutating names are outside the Action | Action has no push step | No new denial test was added in this rehearsal |
| Traceability | Foundation `AuditEvent` and server `AuditEventOut` | Hosted test job passed; events not sampled | No new event schema |
| Recovery | Release rollback is "revert the merge" | Not rehearsed | REL-01 open |
| Benchmarks | Offline benchmark scripts exist on older branches | Not run on `f3b87fb` here | PERF-01 open |

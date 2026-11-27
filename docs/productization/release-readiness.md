# Release readiness

Labels: PASS, FAIL, BLOCKED, NOT TESTED. Documentation being present does not move a row to PASS.

## v0.1 technical MVP

| Gate | State | Why |
| --- | --- | --- |
| Existing core tests remain passing | FAIL | Full local suite on 2026-11-05 exited 1 on one new string. That string was edited and the single detector test passed. The full suite was not re-run, so this gate stays FAIL. |
| One installable GitHub Action | PASS | `action.yml` is a composite action. Local entry-point tests pass. |
| One supported failing workflow diagnosed | PASS | Local fixture only. Not a GitHub-hosted workflow run. |
| JSON and Markdown | PASS | Local test writes both. |
| Credentials redacted | PASS | Local hostile-log test. The redactor is not complete. |
| Security checks | PASS | Local tests listed in `docs/productization/action-security.md`. No external security review. |
| Install instructions reproducible | PASS | `docs/productization/install-github-action.md` matches the inputs. |
| Unsupported features disclosed | PASS | `docs/productization/mvp.md`. |
| GitHub-hosted execution of this change | NOT TESTED | Not observed. |

v0.1 is not a release tag.

## v0.2 external validation

Every row is NOT TESTED. No independent user has been recorded.

## v0.3 paid validation

Every row is NOT TESTED. Three paying customers, margin, and a referral are targets, not results.

# Threat model (audit rehearsal)

This restates controls that are in the tree. It is not a penetration test and not a certification.

| Asset | Threat | Control in tree | Evidence | Residual |
| --- | --- | --- | --- | --- |
| CI log text | Prompt injection or `::` workflow commands | `clean_untrusted` before doctor output | `tests/test_doctor_action.py` on earlier commits; not re-run on `f3b87fb` in this session | A client can still obey the log. |
| Secrets in logs | Leak into the report or summary | `sanitize_text`; `redact-secrets: false` is rejected | Same test module | Unknown secret shapes pass through. |
| Suggested shell commands | The Action executes them | The Action process only launches its Python module | Code inspection of `action.yml` | Another workflow could run commands. This Action does not. |
| Forked PR code | Untrusted checkout via `pull_request_target` | No `pull_request_target` trigger. `self-heal` compares that string and refuses it, and is dispatch-only. | `git grep` on `origin/main` workflows | Write-scoped workflows remain in the repo. |
| GitHub token | Printed on API errors | Error path redacts token shapes | Existing doctor action test | Not a general token vault. |
| Default branch | Automatic merge | Auto-merge job condition is `if: false` | `auto-merge-after-checks.yml` | Someone can edit the condition later. |
| Multi-tenant use | One process sees another's logs | Not designed. Stdio and Actions are single-repo. | No cross-tenant test was run | Do not host the doctor as a shared service. |

## Security tests this session

Not executed locally. The hosted `ci` test job on `f3b87fb` succeeded, which runs the suite including security tests, but this rehearsal did not download the log or name each assertion.

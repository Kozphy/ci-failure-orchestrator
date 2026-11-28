# Threat model for the CI diagnosis plugin

Scope: the v0.1 stdio server and the `diagnose_saved_log` tool. This is a design record of controls in this slice, not a penetration test.

| Threat | What this slice does | Residual risk |
| --- | --- | --- |
| Prompt injection in a CI log | `clean_untrusted` neutralizes `::` workflow commands. The result sets `untrusted: true` and the skill says to treat text as data. | A model client can still obey the log if it ignores the skill. The server cannot force the client. |
| Untrusted CI logs | The only engine call is `diagnose_log` on the supplied string. `evidence_class` is `saved_log`. | The doctor can mis-classify. That is a product limit, not a shell execution. |
| Credential leakage | Returned strings and the audit line pass through `sanitize_text`. The audit record has no log field. | The redactor is a pattern list. Unknown secret shapes can remain in `log_excerpt`. |
| Arbitrary command execution | Tool names `shell`, `exec`, `apply`, `merge`, `push`, `delete`, and `fix-repo-apply` return `approval_required`. No subprocess is started. | The existing CLI on the same machine can still run those commands if a human or another process invokes it. |
| Filesystem scope | The tool takes no path. The server does not read the workspace. `--audit-log` writes only when set, and only the activation line. | A caller who points `--audit-log` at a sensitive path can append there. The default is off. |
| Approval gates | Mutating names fail closed. The skill tells the client to stop. | There is no second human prompt inside the server. Approval means "this process will not do it." |
| Multi-tenant use | One process, one stdin, no tenant id, no shared database. | Do not expose this stdio server on a network. A shared host can see the log the client sends. No tenant isolation is implemented. |

Out of scope: GitHub token handling inside `ci-audit-collect` and `diagnose_run`. Those functions are not called.

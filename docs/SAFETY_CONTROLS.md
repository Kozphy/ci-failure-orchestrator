# Safety controls

How CI Failure Orchestrator keeps automated repair from changing code it should not. Each
control lists what enforces it today and where it stops. "Partial" and "Not implemented" are
stated plainly; do not read this page as a production-readiness claim.

The rule behind all of them: **the system never modifies a repository without a recorded
approval, and never merges.** `fix-repo` only writes disposable worktrees. `fix-repo-apply` is
the single code path that writes to the target repository, and it only creates a new branch
(optionally pushed, optionally with a *draft* pull request).

## Control status

| Control | Status | Enforced by | Limits |
| --- | --- | --- | --- |
| Approval before any write | Enforced | `service/apply.py` refuses unless the durable run state is `APPROVED` (policy or `foundation-decide --action APPROVE`) and the remediation state is not blocking (`POLICY_REJECTED`, `NOT_FIXED`, `REGRESSION_DETECTED`, `HUMAN_REVIEW_REQUIRED`). | Policy rules are heuristic; see [Policy](#policy-rules). |
| No merge | Enforced | No merge call exists in canonical code; `tests/test_module_boundaries.py` fails on any merge API string. PRs are always created with `--draft`. | A human can still merge a bad draft PR. |
| Dry run | Enforced | `fix-repo-apply --dry-run` runs every gate, checks the patch applies to the base commit with `git apply --cached --check` on a temporary index, and writes no git object, branch, remote, audit event or report. `fix-repo` itself only writes worktrees and artifacts. | |
| Protected branches | Enforced | `main`, `master` and the remote's default branch are refused; existing local or remote branches are never overwritten. | Other protected branches must be configured on the Git host. |
| Patch integrity | Enforced | The applied patch must match the verified patch hash and file list, and the resulting commit may only touch those files. | |
| Structural patch refusal | Enforced | `service/patches.py::patch_violation` rejects symlinks, submodules, binary patches, paths outside the repo or inside `.git`, and added lines containing high-confidence secrets. | |
| Permission boundaries | Enforced | Verification and provider commands run without a shell (`shlex` argv), in disposable worktrees, with an environment allowlist; credential-looking variable names are refused (`blocked_env_names`). | Commands run as the operator's OS user; there is no container or VM isolation. |
| Max file-change limit | Partial | Policy auto-approves at most 3 changed files (`auto_approve_max_files`); more than 8 files is broad scope (POL-010) and escalates. | Escalation, not a hard reject: a human can still approve a large patch. |
| Max retry budget | Enforced | Default 3 attempts. `--max-attempts` outside 1 to 10 is refused (`MAX_ATTEMPTS_CEILING`). Identical failures, identical proposals and no-progress attempts stop the loop early (`foundation/retry.py`). Reaching the limit escalates (POL-011). | |
| Max agent/tool budget | Partial | Attempts are capped, and every provider call and verification command has a timeout. | No token, cost or tool-call budget: provider commands do not report usage. |
| Allowed command policy | Partial | Commands are operator-supplied on the command line or in the verification config; patches that weaken verification are flagged (POL-018, POL-019). | No allowlist of executables. Anyone who can run the CLI chooses the commands. |
| Secret redaction | Enforced | Logs, prompts and stored evidence pass through `foundation/sanitization.py` and the untrusted-text cleaner before storage or provider calls. | Pattern based; an unusual secret format can slip through. |
| Audit logging | Partial | Every decision and side effect (`TARGET_PATCH_APPLIED`, `TARGET_BRANCH_PUSHED`, `TARGET_PR_OPENED`) is appended to `runs/<run_id>/events.jsonl` with a monotonic sequence and unique event IDs; `fix-repo-report` renders the evidence. | Local files, not tamper-evident (no hash chain or signing). |
| Rollback path | Enforced | The target working tree, index and current branch are never touched. Every apply result lists `rollback` commands that undo exactly what it wrote: close the PR, delete the remote branch, delete the local branch. | Rollback commands are printed for a human to run, not executed automatically. |
| Human escalation | Enforced | Default policy outcome is ESCALATE. Unknown or environment failures (POL-014), low classification confidence (POL-015), security-sensitive, auth, dependency, CI workflow, infrastructure and broad changes all escalate. | |
| Timeouts | Enforced | Verification and provider commands: 600 s default. Git: 120 s, push 300 s. `gh pr create`: 300 s. A timed-out push or PR creation returns `PARTIAL` with a note that the remote side may already exist, instead of crashing. | `git worktree remove` during sandbox cleanup has no timeout. |

## Policy rules

The static policy engine (`foundation/policy.py`) is authoritative; a model never overrides it.
Rule IDs as they appear in `policy_rules` output:

`POL-001` evaluation must pass, `POL-002` forbidden path, `POL-003` security-sensitive change,
`POL-004` CI workflow change, `POL-005` low-risk auto-approve, `POL-006` default escalation,
`POL-007` dependency change, `POL-008` restricted tool, `POL-009` auth change, `POL-010` broad
scope, `POL-011` high retry count, `POL-012` invalid proposal, `POL-013` engine failure,
`POL-014` environment or unknown failure, `POL-015` low classification confidence, `POL-016`
escalation path, `POL-017` infrastructure or migration, `POL-018` verification weakened,
`POL-019` verification change review.

## Approval policy in practice

| Situation | Result |
| --- | --- |
| Patch passes verification, small scope, known failure class | Policy APPROVE; `fix-repo-apply` may create a branch. Real CI must still pass before the repair counts as `VERIFIED_FIXED`. |
| Patch passes verification but touches auth, CI workflows, dependencies or infrastructure | ESCALATE; a human decides with `foundation-decide`. |
| Failure class unknown or confidence below 0.6 | ESCALATE, even when the patch passes. |
| Regression detected, or the target test still fails | Blocked; apply refuses. |

## Known gaps

These are not implemented and are not claimed:

- Container or VM isolation for verification and provider commands.
- An executable allowlist for verification commands.
- Token, cost or tool-call budgets for model providers.
- Tamper-evident (hash-chained or signed) audit logs.
- Hard rejection of large patches (they escalate instead).
- A timeout on sandbox worktree cleanup.

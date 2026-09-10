# Pull-request readiness analysis

`analyze-pr` evaluates the exact proposed change rather than only repository-wide controls.

```bash
ci-orchestrator analyze-pr --repo owner/repo --pr 42
```

For private repositories, provide `GITHUB_TOKEN` or `--token`.

## Evidence flow

```text
Pull request
   ↓
PR metadata + exact head SHA
   ↓
Changed files
   ↓
Review states
   ↓
Combined commit status
   ↓
Head-SHA workflow runs
   ↓
Deterministic change-risk findings
   ↓
PR_READY / BLOCK
```

The command is read-only and intentionally fail-closed for merge authority.

## Change-surface classification

Changed files are classified into source, tests, workflows, dependency/build manifests, documentation, and security/policy-sensitive paths. The report also records additions, deletions, and total changed lines.

This classification is heuristic and path-based. It is evidence for review routing and policy decisions, not a semantic proof that a file is safe or unsafe.

## Blocking conditions

The current policy blocks when any of these conditions hold:

```text
SOURCE_CHANGE_WITHOUT_TEST_CHANGE
SECURITY_SENSITIVE_CHANGE_UNAPPROVED
CHANGES_REQUESTED
CI_FAILED
CI_PENDING
NO_CI_EVIDENCE
```

`PR_READY` therefore requires exact-head CI evidence to be complete and green, no unresolved latest review requesting changes, and no unmitigated high-risk change condition.

Medium findings such as `CI_WORKFLOW_CHANGED`, `DEPENDENCY_OR_BUILD_CHANGE`, or `LARGE_CHANGESET` remain visible but do not automatically veto a PR. This keeps warnings distinct from merge authority.

## Review semantics

Only each reviewer's latest submitted review state is counted. Earlier approvals do not override a later `CHANGES_REQUESTED`, and an older `CHANGES_REQUESTED` does not remain blocking after the same reviewer submits a newer approval.

## CI semantics

The analyzer evaluates evidence against the PR head SHA. It combines GitHub's commit status with workflow-run state:

```text
PASS        completed, non-failing head-SHA evidence
PENDING     at least one relevant run/status is still pending
FAIL        failed/error/cancelled/timed-out/action-required evidence
NO_EVIDENCE no successful head-SHA CI evidence was found
```

A pending or missing CI state blocks `PR_READY`; the tool does not infer readiness from source inspection alone.

## Exit codes

```text
0  PR_READY
2  BLOCK
```

This allows `analyze-pr` to become a CI policy gate later.

## Intended composition

```text
analyze-repo
   ↓
repository engineering intelligence
   ↓
analyze-pr
   ↓
change surface + reviews + exact-head CI
   ↓
review/static-analysis aggregation
   ↓
independent verification
   ↓
PR_READY / BLOCK
   ↓
REPAIR_SUCCESS
   ↓
RELEASE_READY
   ↓
PRODUCTION_SUCCESS
```

Repository-wide risk remains context rather than automatically blocking every PR because of unrelated legacy debt. Future versions can add explicit policy profiles for organizations that want stricter baseline enforcement.

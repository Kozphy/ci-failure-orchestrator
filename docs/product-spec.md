# CI Doctor product specification

Status: draft for review, 2026-10-04. Brand: **CI Doctor**. Package and command:
**`actions-doctor`** (decided 2026-10-04, because `ci-doctor` is taken on PyPI; see
[productization-audit.md](productization-audit.md), section 1). The Python import path
stays `ci_failure_orchestrator` until a separate, reviewed rename.

**Positioning.** Diagnose CI failures, propose safe fixes, verify the repair, and leave
auditable evidence.

**Who it is for.** Maintainers and platform engineers of GitHub Actions repositories who
lose time reading failed logs, re-running flaky jobs, and fixing the same classes of
breakage by hand.

## 1. Product rules

These rules come from the existing safety model and constrain every interface below.

1. **Evidence first.** Every diagnosis line points at evidence: a job, a step, and a log
   line range. If there is no evidence, the class is `unknown`, and the output says so.
2. **Honest confidence.** Confidence comes from deterministic rules and is labeled
   "heuristic" until it is calibrated against labeled runs (see [metrics.md](metrics.md)
   when written). No percentages are shown for heuristic confidence; it is shown as high,
   medium or low.
3. **Deterministic control plane.** A model may propose a patch. Only the control plane
   decides: the evaluator runs the checks, the policy engine (rules POL-001..015) approves,
   rejects or escalates, and the retry budget stops retries.
4. **Read-only by default.** `analyze`, `explain` and `report` never write to a
   repository. `propose` and `verify` write only to a temporary worktree. `repair` is the
   only command that writes, it needs an APPROVE decision, and it only opens a draft pull
   request on a new branch. Nothing merges.
5. **Human approval for anything not low-risk.** Dependency, auth, CI-workflow,
   security-sensitive, broad-scope, environment and unknown failures always escalate.
6. **Same engine everywhere.** The CLI, the Action and any future surface call the same
   library code. No surface has its own repair or policy logic.

## 2. Command-line interface

### 2.1 Commands

| Command | What it does | Writes | Built from |
|---|---|---|---|
| `analyze` | Diagnose one failed run or one saved log. | Nothing (optional `--out` artifact) | `github_client`, `ci_audit.collect` (log sectioning, message, step refinement), foundation `FailureClassifier`, policy preview |
| `explain` | Show what happened in a stored diagnosis or repair attempt, as a timeline. | Nothing | `foundation-inspect`, `foundation-events`, task store |
| `propose` | Produce a candidate patch for a diagnosis, from a provider or a supplied patch file. | Audit artifacts only | `ProposalSource`, `OptionalModelPlannerAdapter` |
| `verify` | Reproduce the failure, apply the patch in a temporary worktree, re-run the checks, and evaluate policy. | Temporary worktree, audit artifacts | `fix-repo` (`service/`, `repo_fix.py`) |
| `repair` | Record a human decision, then open a draft pull request with the verified patch. | New branch and draft PR | `foundation-decide`, `fix-repo-apply` |
| `report` | Summarize one attempt, or 30 days of a repository's CI. | Report file | `ci-audit-collect`, `ci-audit-report`, foundation operations report |

The existing `ci-orchestrator` commands stay as the engine-level interface. The product
commands are thin wrappers that change naming, input handling and output, not behavior.

### 2.2 Inputs

```
actions-doctor analyze --repo owner/repo --run 123456 [--attempt N] [--job NAME]
actions-doctor analyze --url https://github.com/owner/repo/actions/runs/123456
actions-doctor analyze --log failed-job.log            # offline, no token
actions-doctor explain CID-20261004-3f2a9c1e
actions-doctor propose CID-20261004-3f2a9c1e --patch fix.diff | --provider NAME
actions-doctor verify  CID-20261004-3f2a9c1e --repo-path . [--command "pytest -q"]
actions-doctor repair  CID-20261004-3f2a9c1e --approve --reviewer alice
actions-doctor report  --repo owner/repo --days 30 [--format md|json]
actions-doctor report  CID-20261004-3f2a9c1e
```

Common flags: `--json` (machine output with the same fields), `--out DIR` (artifact
directory), `--token` (defaults to `GITHUB_TOKEN`, never printed or stored).

Exit codes: `0` diagnosis produced (any class, including `unknown`); `2` usage error;
`3` GitHub or input error; `4` policy rejected or escalated (for `verify` and `repair`,
so scripts can branch on it).

**Audit IDs.** `CID-<UTC date>-<first 8 hex of the run hash>`, derived from the existing
foundation run ID. No counter or database is needed, so the Action can create them
statelessly. A saved log gets `CID-log-<first 8 hex of the log's SHA-256>`, so the same log
always gets the same ID. The brief's sequential form (`CID-2026-000142`) would need a shared counter.

### 2.3 `analyze` output

Example from the dependency demo scenario (synthetic; every value comes from the saved log
and the existing rules):

```
CI Doctor · analyze · demo/dependency-drift (saved log)

Failure class    dependency_failure                     confidence: high (heuristic)
Evidence         job "tests" › step "Install dependencies" › log lines 41-43
                 ERROR: Cannot install requests==2.32.3 and urllib3==1.26.20 because
                 these package versions have conflicting dependencies.
Failing command  pip install -r requirements.txt
Affected jobs    tests (failed) · integration (skipped, depends on tests)

Root-cause candidates
  1. tests › Install dependencies   dependency conflict    first failure in run order
  2. integration                    skipped               downstream of 1

Next step        Resolve the version conflict named in the resolver message: relax or
                 update the pin on urllib3 or requests in requirements.txt.
Verification     re-run: pip install -r requirements.txt && pytest -q
Policy preview   ESCALATE before any repair
                 POL-014 dependency failures need a human · POL-007 dependency files changed
Recommended      actions-doctor propose CID-20261004-3f2a9c1e --patch <your fix>
                 then actions-doctor verify, then a reviewer runs actions-doctor repair --approve

Audit            CID-20261004-3f2a9c1e  (artifacts/runs/run-3f2a9c1e…/)
```

Notes on each field:

- **Failure class.** The foundation taxonomy (see [failure-taxonomy.md](failure-taxonomy.md)
  when written): test, lint, type, build, dependency, network, infrastructure,
  configuration, flaky, unknown, security scan. A security scan finding always escalates
  (POL-014); CI Doctor never proposes code for it.
- **Confidence.** Mapped from the rule that matched: a specific `##[error]` line with a
  known pattern is high, a step-name refinement is medium, a fallback summary is low.
  Reported as heuristic until calibration exists.
- **Evidence.** The failing section is already isolated by `ci_audit.collect.failing_section`.
  Line ranges need one small change: keep the original line indices when sectioning.
- **Failing command.** Taken from the `##[group]Run <command>` header of the failing
  step, which the sectioning already preserves.
- **Affected jobs and ranking.** v0.1 ranks by run order and evidence specificity using
  the jobs API (start times, conclusions, skipped jobs). v0.2 reads `needs:` from the
  workflow file at the run's commit (service plan Stage 4) so that "downstream of" is
  exact rather than inferred.
- **Next step.** A fixed playbook sentence per class, filled with names from the evidence
  (package, tool, file). It is deterministic text, not generated advice. Example
  remediations such as "pin urllib3<2.3" are only shown when that exact constraint is in
  the evidence.
- **Policy preview.** The rules that will apply to any repair of this class, evaluated
  before a proposal exists, so the user knows up front whether a repair can be automatic.
- **When nothing matches.** The output says `unknown`, shows the failing section, and
  says that no rule matched. It never invents a cause.

### 2.4 `verify` and `repair` output

```
CI Doctor · verify · CID-20261004-3f2a9c1e (demo scenario)

Reproduced       yes · pip install -r requirements.txt failed on the base commit
Patch            requirements.txt (+1 -1)
Re-run           pip install -r requirements.txt   passed
                 pytest -q                         passed (212 tests)
Evaluation       PASS
Policy           ESCALATE · POL-007 dependency files changed · POL-014 dependency failure
Retry budget     1 of 3 attempts used
Next             A reviewer with write access runs:
                 actions-doctor repair CID-20261004-3f2a9c1e --approve --reviewer <name>
```

`repair` records the decision with the reviewer's name, applies the verified patch on a
new branch, opens a draft pull request whose body links the audit trail, and prints the
PR URL. The commit is built on the exact base commit that was verified, and `repair`
refuses if the patch digest or the changed files differ from what was verified (existing
`fix-repo-apply` behavior). If the target branch has moved on, the draft PR shows that
through GitHub's normal conflict and status checks.

### 2.5 CLI framework

Keep argparse and add a small text renderer. The package has one runtime dependency
(PyYAML); adding Click, Typer or Rich would improve help text and colors slightly but adds
dependencies for every user and every Action run. Colors use plain ANSI codes and switch
off when output is not a terminal or `NO_COLOR` is set.

## 3. GitHub integration

### 3.1 Action first, App later

A reusable Action ships first (service plan §5.1). It needs no hosted service, no webhook
secret and no app installation, and it runs with the repository's own `GITHUB_TOKEN`. A
GitHub App comes later, once the Action has users who need cross-repository installation,
interactive commands, or no per-repository workflow file.

### 3.2 Workflow shape

```yaml
# .github/workflows/actions-doctor.yml (in the user's repository)
on:
  workflow_run:
    workflows: [CI]
    types: [completed]

jobs:
  diagnose:
    if: github.event.workflow_run.conclusion == 'failure'
    runs-on: ubuntu-latest
    permissions:
      actions: read          # read jobs and logs
      contents: read
      pull-requests: write   # one comment on the PR
    steps:
      - uses: OWNER/actions-doctor-action@v0
        with:
          mode: diagnose      # diagnose | propose
```

Security properties:

- **No `pull_request_target`.** `workflow_run` runs the default-branch workflow, so the
  configuration is trusted. The diagnose job never checks out or executes code from the
  pull request; it only reads the API and logs.
- **Verification of PR code runs without write access.** When `mode: propose` verifies a
  patch, that job has `contents: read` only and no secrets. A separate job, triggered only
  by an approval, has `contents: write` and `pull-requests: write` to open the draft PR.
- **Configuration comes from action inputs and a file on the default branch**, never from
  the pull request.
- **Logs are redacted** before they are written to any artifact or comment; the comment
  quotes at most the evidence lines.
- **Retry budget.** The Action does not re-run workflows. Re-run suggestions for flaky
  failures are advice in the comment, and the budget counts proposals and verifications
  per failure.

### 3.3 Pull request comment

One comment per pull request, updated in place (found by a hidden marker), not a new
comment per failure.

```markdown
<!-- actions-doctor -->
## CI Doctor diagnosis

**Run:** CI #482 · commit 3f2a9c1 · failed 2 of 5 jobs

| | |
|---|---|
| Failure class | `dependency_failure` (confidence: high, heuristic) |
| Where | `tests` › Install dependencies · [log lines 41-43](https://github.com/OWNER/REPO/actions/runs/123456/job/789#step:4:41) |
| Affected | `tests` failed · `integration` skipped (depends on `tests`) |

> ERROR: Cannot install requests==2.32.3 and urllib3==1.26.20 because these package
> versions have conflicting dependencies.

**Next step:** relax or update the pin on `urllib3` or `requests` in `requirements.txt`.

**Repair:** needs human approval (POL-014 dependency failure, POL-007 dependency change).
A maintainer can add the label `actions-doctor:approve` to let CI Doctor open a verified
draft PR.

<sub>Audit ID CID-20261004-3f2a9c1e · [evidence artifact](…) · CI Doctor never merges.</sub>
```

### 3.4 Approval

GitHub does not support buttons in comments, so "[Approve Repair]" is not possible as a
button. The approval paths are:

| Phase | Mechanism | Check |
|---|---|---|
| Action (v0.3–v0.6) | A maintainer adds the label `actions-doctor:approve`, or runs a `workflow_dispatch` with the audit ID. | The Action checks the actor has write permission through the API and records the reviewer in the audit trail. |
| App (later) | `/actions-doctor approve CID-…` comment, or a check-run action button. | The App verifies the webhook signature and the commenter's permission, using short-lived installation tokens. |

Approval only allows a draft PR. The PR still goes through the repository's normal review
and branch protection.

## 4. Web dashboard (concept only)

Not built until the CLI and Action have users. The first version is a static HTML report
generated from the same artifacts (`actions-doctor report --format html`), not a hosted
service.

### 4.1 Overview page

| Metric | Definition |
|---|---|
| Default-branch success rate | Successful runs on the default branch ÷ completed runs, 30 days. Shown as the headline instead of an opaque health score. |
| Health score (optional) | Only shown with its components: success rate, flaky-failure share, median time to repair. The formula is printed next to the number. |
| Failures per week | Failed runs per ISO week. |
| Top failure classes | Count and share per class, with an "unknown" share always shown. |
| Retry success rate | Failures classified flaky whose re-run passed ÷ flaky failures re-run. |
| MTTD (mean time to diagnose) | Failure conclusion time → diagnosis posted. |
| MTTR (mean time to repair) | Failure conclusion time → next successful run of the same workflow on the same branch. |
| Automated repairs | Draft PRs opened after an automatic APPROVE, and how many merged. |
| Human escalations | Decisions that went to a person, by rule. |

### 4.2 Failure detail page

Failure → evidence (log lines, step, job) → classification and the rule that matched →
root-cause candidates → repair proposal (diff) → verification (commands and results) →
policy decision with rule IDs → human decision (reviewer, time) → outcome (draft PR,
merged or closed, next run result).

### 4.3 Audit trail page

The hash-chained event log for one attempt: who or what acted, what changed, which policy
applied, what was verified, who approved, and a link to the draft PR. Includes the
`foundation-verify` result, so a reader can see that the log was not altered.

## 5. What this spec deliberately leaves out

- Automatic merging, automatic re-runs, and repairs to CI workflow files.
- AI-generated root causes without evidence lines.
- A hosted API, MCP server or agent skill (extension points only; see the roadmap).
- Per-seat pricing and accounts (see `commercialization.md` when written).

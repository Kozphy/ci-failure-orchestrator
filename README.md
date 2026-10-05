# CI Failure Orchestrator

**Know why CI failed, get a fix that is proven before it lands, and keep a person in charge of every merge.**

> **GitHub CI Reliability Audit**: fixed price, read-only, one repository, report in 3 business days.
> Pilot price **US$149** (first 3 clients). **[See pricing and book →](#pricing-and-booking)**

## Stop fixing CI failures manually

A red build costs the same hour every time: open the log, scroll past 10,000 lines, guess
whether it is the code, a flaky test or the runner, rerun it, and hope. AI coding tools can
write a patch, but a patch that turns CI green is not the same as a correct one. Deleting the
failing test, skipping it or lowering a coverage threshold also turns CI green.

CI Failure Orchestrator diagnoses the failure, checks a candidate fix against the original
failure and your own regression and quality gates, and hands the result to a policy engine
that decides what may happen next. It opens a draft pull request at most. It never merges.

**Who it is for:** small engineering teams (3–30 developers) on GitHub Actions with a pytest
suite, red builds that get rerun instead of read, and AI assistants starting to propose CI
fixes that someone has to trust.

## What it does

- **Diagnoses failures** from a GitHub Actions run or a saved log: failure class (test, lint
  or type, dependency, network, timeout, configuration, environment), the evidence line, and
  the next step. Read-only.
- **Verifies repairs** in a disposable git worktree: the failure must reproduce at the base
  commit, the failing tests must pass with the patch, and your regression suite and quality
  gates must not get worse. The patch comes from you, a teammate, or any LLM CLI you choose.
- **Refuses fake fixes**: deleted, skipped or weakened tests, lowered coverage or quality
  gates, and removed CI steps are rejected by deterministic checks, not by a model.
- **Gates by policy**: 19 rules decide approve, reject or escalate. The default is escalate.
  Auth, CI configuration, dependencies, secrets, broad diffs and low-confidence diagnoses go
  to a person.
- **Writes an evidence report** per repair: what broke, why, what changed, which tests ran,
  what shows it is safe, and what risk remains.
- **Audits CI reliability** over 30 days of history: failure and rerun rates, flaky signals,
  duration and estimated wasted minutes.

## How it works

```text
CI failure (GitHub Actions run or log file)
  → diagnose            classify the failure, keep the evidence line
  → reproduce           run your verify commands at the base commit; they must fail
  → propose             patch file, or an LLM CLI behind an interface
  → verify              targeted tests, regression suite, quality gates, before vs after
  → policy gate         APPROVE | REJECT | ESCALATE (default: ESCALATE)
  → apply (optional)    new branch + draft PR; your working tree and main are untouched
  → real CI check       read the CI result for that commit → VERIFIED_FIXED or not
  → evidence report     Markdown + JSON, with an append-only event log
```

Retries are finite (at most 10 attempts), and the provider sees the previous failure on each
retry. A model never decides the outcome: the final state comes from one deterministic
function over collected evidence, and evidence that was not collected never counts as a pass.

## Why verified repair matters

> A green pipeline is necessary evidence, but it is not sufficient evidence of a correct repair.

Every repair ends in one of these states:

| State | Meaning |
| --- | --- |
| `VERIFIED_FIXED` | Failure reproduced and resolved, no regressions, quality gates preserved, policy passed, real CI confirmed |
| `POLICY_APPROVED` | All local evidence is in; real CI has not reported yet |
| `CI_GREEN_BUT_UNVERIFIED` | Real CI passed, but some evidence is missing |
| `HUMAN_REVIEW_REQUIRED` | High-risk change, policy escalation, or real CI failed |
| `REGRESSION_DETECTED` | Something that passed before the patch fails after it |
| `NOT_FIXED` | The original failure is still there, or a different error replaced it |
| `POLICY_REJECTED` | Tests deleted, skipped or weakened; gates lowered; CI steps removed |

The primary metric is the **verified repair rate**. The CI green rate is reported only next to
it, so the gap between the two stays visible.

## Quick Start

Requirements: Python 3.10+ and git. The demo runs in under a minute with no token, network or
model.

```bash
git clone https://github.com/Kozphy/ci-failure-orchestrator.git
cd ci-failure-orchestrator
pip install -e ".[dev]"

# The end-to-end demo: a real bug, a red CI run, a verified repair, an evidence report
python examples/demo-repo/run_demo.py
```

On your own repository:

```bash
# 1. Diagnose a failed CI log (read-only)
actions-doctor diagnose --log ci-failure.log

# 2. Verify a candidate fix; nothing in ../my-service is written
ci-orchestrator fix-repo --repo-path ../my-service \
  --verify "python -m pytest tests/test_calc.py -q" \
  --patch-file fix.patch --verification-config verify.yml

# 3. See what apply would do, then create a branch and a draft PR
ci-orchestrator fix-repo-apply <run_id> --dry-run
ci-orchestrator fix-repo-apply <run_id> --push --open-pr

# 4. Record the real CI result, and read the evidence report
ci-orchestrator fix-repo-verify-ci <run_id> --repository me/my-service --wait 900
ci-orchestrator fix-repo-report <run_id>
```

To let a model propose the patch, replace `--patch-file` with
`--provider-cmd "claude -p" --provider-env ANTHROPIC_API_KEY` (any CLI that reads a prompt on
stdin and prints a diff). To diagnose every failed run automatically, add the
[CI Doctor GitHub Action](docs/ENGINEERING.md#github-action-diagnosis-in-the-job-summary).

## Example

The [demo repository](examples/demo-repo/README.md) is a small Python package whose
`is_newer("1.10.0", "1.9.0")` returns `False` because versions are compared as strings.

1. CI fails: `FAILED tests/test_versions.py::test_is_newer_handles_double_digit_minor`.
2. `actions-doctor diagnose` classifies it as a test failure and quotes the failing line.
3. `fix-repo` reproduces the failure at the base commit, applies a one-line fix, reruns the
   failing test, the regression suite, a build check and one behavioral invariant, and the
   policy engine approves it.
4. `fix-repo-apply` creates a fix branch; `main` is untouched and nothing is pushed.
5. `fix-repo-report` writes the evidence report.

The demo ends at `POLICY_APPROVED`, not `VERIFIED_FIXED`, because no real CI runs in it. The
patch is a recorded teammate fix, not model output. It is one bug in one repository, so no
success rate should be inferred from it.

Real results so far, all on our own repositories:

- **Audit:** 30 days and 957 workflow runs on Windows-Network-Recovery-Toolkit. Windows jobs
  used 39% of about 5,650 Linux-equivalent minutes, and cancelled jobs another 17%. A PR that
  takes Windows jobs off the per-PR path passed all checks; the post-merge measurement is
  pending. [Sample audit report](docs/sample-audit-report.md) from this repository's history.
- **Fix verification:** a 4-file type-check fix went from a failing baseline to type check and
  full test suite passing in a disposable worktree, then escalated to a person by policy rule
  POL-008, as designed.
- **Offline scenarios:** `actions-doctor demo --all` runs six failure types (dependency drift,
  flaky test, network, timeout, configuration, environment); all six escalate, each for a
  stated policy reason.

## Safety model

| Control | How it is enforced |
| --- | --- |
| No merging | No code path merges. Apply creates a branch and, if asked, a draft PR |
| Protected branches | Apply refuses `main`, `master` and the remote's default branch, and never overwrites an existing branch |
| Patch integrity | Apply checks the hash of the patch that was verified |
| Dry run | `fix-repo-apply --dry-run` runs every gate and writes nothing |
| Rollback | Every apply result lists the commands that undo it |
| Finite retries | 1 to 10 attempts; identical or non-improving patches stop early |
| Escalation by default | Unknown failures, confidence below 0.6, more than 8 files, auth, CI, dependency and secret changes go to a person |
| Provider isolation | The model CLI runs without a shell, in an empty directory, with an environment allowlist |
| Redaction | Tokens and secrets are scrubbed before anything is written |
| Timeouts | Verify and provider commands, git, push and PR creation all time out; a timed-out push or PR is reported as partial, not crashed |

Known gaps, stated plainly: no container isolation for verify commands, no command allowlist,
no cost budget, and the audit log is append-only but not tamper-evident. Full list:
[docs/SAFETY_CONTROLS.md](docs/SAFETY_CONTROLS.md).

## Architecture

A Python package with two CLIs over one deterministic core:

- `ci_failure_orchestrator/foundation/`: classifier, planner, sandbox, evaluator, retry
  budget, policy engine, escalation, durable state and audit events.
- `ci_failure_orchestrator/service/`: the `fix-repo` pipeline (ingest, reproduce, propose,
  verify, apply, real CI check, evidence report, metrics).
- `ci_failure_orchestrator/doctor/`: `actions-doctor` diagnosis, the offline demo and the
  GitHub Action.
- `ci_failure_orchestrator/ci_audit/`: the read-only reliability audit.

Everything runs locally or in your CI runner; there is no hosted service. Details:
[docs/COMMERCIAL_ARCHITECTURE.md](docs/COMMERCIAL_ARCHITECTURE.md) and
[docs/ENGINEERING.md](docs/ENGINEERING.md).

## Supported CI providers

| Provider | Support |
| --- | --- |
| GitHub Actions | Run and log ingestion, the CI Doctor action, real CI verification, draft PRs, reliability audit. The API adapter is tested against recorded responses |
| Any CI with text logs | `actions-doctor diagnose --log` and `fix-repo` with your own verify commands. No native API integration |
| GitLab CI, Jenkins, CircleCI, Buildkite | Not integrated yet |

## Current limitations

- **No production users yet.** Evidence so far is one real audit, one real fix verification on
  our own repositories, synthetic benchmarks and the demo. None of it is a production success
  rate.
- Patch quality depends on the patch source. With `--provider-cmd`, the model writes the patch;
  this project only verifies it.
- Verify commands run on your machine or runner without container isolation.
- Model token usage and cost are not measured; `fix-repo-metrics` reports them as not
  instrumented.
- Escalation produces a local review package; there is no Slack or email notification.
- The audit log is append-only, not cryptographically tamper-evident.
- Python projects are the tested path; other languages work only through your own verify
  commands.

## Pricing and booking

The code is [MIT licensed](LICENSE): you can run it yourself for free. If you would rather have
someone run it, read the results and fix what it finds, these are fixed-price services:

| Service | What you get | Time | Price |
| --- | --- | --- | --- |
| **CI Reliability Audit** | Read-only review of one repository's last 30 days of GitHub Actions: failure causes, flaky tests, wasted minutes, ranked fixes, 30-day plan, 20-minute call. [Details](docs/ci-reliability-audit.md) | 3 business days | **US$149** for the first 3 clients, then US$199 |
| **CI Fix Sprint** | The audit, plus the top 3 fixes as pull requests for your review, CI Doctor on every failed run, and a re-measurement after 2 weeks | 2 weeks | US$900 |
| **Verified Repair Setup** | `fix-repo` wired into your repository: fixes from people or AI assistants are verified against the original failure and your tests before a person merges them | 3–4 weeks | from US$3,500 |
| **Monthly CI Care** | Monthly re-audit, triage of new failure types, policy tuning, one-page report | monthly | from US$400/month |

**Public repository?** Ask for a free CI snapshot: the top 3 findings from your last 30 days,
no access needed.

### How to book

1. **[Book a free 15-minute call](https://cal.com/YOUR-HANDLE/ci-audit)** to check that the audit
   fits your repository, or **[pay for the audit directly](https://buy.stripe.com/YOUR-PAYMENT-LINK)**.
2. Share read-only access: a fine-grained token scoped to the one repository with **Actions:
   Read-only** and **Metadata: Read-only**, expiring in 7 days. Public repositories need nothing.
3. Receive the report within 3 business days, then a walkthrough call if you want one.

Card payment through Stripe; invoices on request. If the audit contains no finding you can act
on, you get a full refund. Questions: [YOUR-EMAIL](mailto:YOUR-EMAIL).

Planned software tiers (Starter, Pro, Team/Enterprise) are described in
[docs/COMMERCIALIZATION_PLAN.md](docs/COMMERCIALIZATION_PLAN.md); there is no billing system for
them yet.

## Roadmap

Next 30 days:

- Run the audit and verified repair with the first pilot customers and publish real results.
- Measure model token usage and cost per repair.
- Run verify commands in a container.
- Send escalations to Slack or email.
- Tag a release so the GitHub Action can be pinned.

Later, and only if pilots ask for it: GitLab CI support, a hosted dashboard, a tamper-evident
audit log, and more languages. Postponed items are listed in the
[commercialization plan](docs/COMMERCIALIZATION_PLAN.md#features-explicitly-postponed).

---

Engineering detail (system model, invariants, sample runs, benchmarks, every command):
[docs/ENGINEERING.md](docs/ENGINEERING.md) · Python package `ci-failure-orchestrator` · CLIs
`ci-orchestrator` and `actions-doctor` · version in `pyproject.toml`.

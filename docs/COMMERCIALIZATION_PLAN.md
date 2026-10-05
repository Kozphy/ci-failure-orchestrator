# Commercialization plan

Date: 2026-10-05. Companion documents: [productization-audit.md](productization-audit.md#0-commercialization-update-2026-10-05)
(state of the code), [ICP.md](ICP.md) (buyer), [COMMERCIAL_ARCHITECTURE.md](COMMERCIAL_ARCHITECTURE.md)
(workflow, product modes, what not to build) and [SAFETY_CONTROLS.md](SAFETY_CONTROLS.md).

There are no paying customers yet. Every price and target below is a hypothesis to test with
the first customers, not a measurement.

## Current maturity

- **Engineering:** M3 (evaluated system) with an M4 human-decision slice, per
  [repository-audit.md](repository-audit.md). The diagnose → reproduce → verify → policy →
  apply → real-CI → evidence loop exists in code and is covered by the automated test suite
  and a golden benchmark held against a reviewed baseline.
- **Proof:** the [end-to-end demo](../examples/demo-repo/README.md) runs from a failing pytest
  run to a verified patch, a fix branch and an evidence report. It ends at `POLICY_APPROVED`,
  because no real CI runs in it. Two real uses on our own repositories: one 957-run reliability
  audit and one 4-file fix verification.
- **Commercial:** no customers, no release tag, not on PyPI, no hosted component, no billing.
  The audit offer is published at US$149 (pilot) then US$199.
- **License:** MIT. Anyone can run the code for free, so revenue has to come from service,
  support and, later, hosted convenience, not from license restrictions.

## MVP definition

A **verified-repair pilot for one GitHub repository**, run by the customer on their own runner:

1. The CI Doctor Action diagnoses every failed run in the job summary.
2. For a chosen failure, `fix-repo` reproduces it, verifies a candidate patch (the customer's,
   a teammate's or their LLM CLI's) against the failing tests, the regression suite and the
   quality gates in `verify.yml`, and applies policy.
3. Approved repairs become a draft PR through `fix-repo-apply`; nothing merges.
4. `fix-repo-verify-ci` records the real CI result; `fix-repo-report` writes the evidence report.
5. Once a month, `fix-repo-metrics` gives the verified repair rate, false-fix catches, time to
   diagnosis and escalation rate.

Everything in steps 1–5 exists in code today. The pilot adds onboarding (writing `verify.yml`
with the customer) and a monthly review. Not in the MVP: hosting, accounts, dashboards,
automatic merging, non-GitHub CI.

## Initial ICP

Small SaaS engineering teams (3–30 engineers) whose main CI is GitHub Actions and whose main
test suite is pytest. The buyer is the engineering lead or the senior engineer who gets pinged
when `main` is red. Scoring and disqualifiers: [ICP.md](ICP.md).

## Core customer problem

Red builds are rerun instead of understood, and the person who owns CI loses hours per week to
reading logs. AI assistants now propose CI fixes, but a fix that turns CI green is not
necessarily correct: deleting, skipping or weakening a test, or lowering a coverage threshold,
also turns CI green. Reviewers have no cheap way to tell the difference.

## Product promise

> When a GitHub Actions run fails, CI Doctor points to the log lines that explain it. Given a
> candidate fix from anyone, it reproduces the failure, reruns the failing tests and your
> regression checks in a disposable worktree, rejects fixes that only make CI green by
> weakening the tests, and writes one evidence report that says whether the change is safe to
> merge and why. It never merges.

## Existing differentiators

- **Verified repair states.** `VERIFIED_FIXED` is separate from `CI_GREEN_BUT_UNVERIFIED`; the
  primary metric is the verified repair rate, with the CI green rate reported next to it.
- **Fake-fix rejection by deterministic checks**: deleted, skipped, renamed-out or weakened
  tests, lowered gates and removed CI steps are rejected without a model's opinion.
- **Model-agnostic.** Any CLI that reads a prompt and prints a diff can propose patches; the
  customer keeps their own model and key.
- **Fail-closed policy.** 19 rules, default ESCALATE, finite retries (at most 10 attempts).
- **Nothing to trust with source code.** Runs on the customer's machine or runner; there is no
  service that receives code or logs.
- **One writer, no merge**, with dry-run and rollback commands.

## Missing capabilities

Ordered by how much they block the first paying customers:

1. **Release and install path**: a tagged release so the Action can be pinned; PyPI later.
2. **Model cost measurement**: token usage and cost per repair are not instrumented, so the
   cost side of pricing is estimated, not measured.
3. **PR comment** with the evidence report summary (today it is a local Markdown file).
4. **Escalation notification** to Slack or email (today it is a local review package).
5. **Container isolation** for verify commands, and a command allowlist.
6. **Test-level evidence beyond pytest** (Jest, Go) for the second wave of customers.
7. **Multi-repository view**, RBAC, SSO, retention: Team/Enterprise only, postponed.

## Recommended packaging

Three packages over one engine. Policy, retry budget and escalation are in every package that
touches code; they are never an upsell.

| Package | What the customer gets | Exists today |
| --- | --- | --- |
| **Starter: Diagnose** | CI Doctor Action on every failed run, `actions-doctor diagnose`, and the 30-day reliability audit report | Yes |
| **Pro: Diagnose + Repair + Verify** | Starter plus `fix-repo` with `verify.yml`, draft PRs, real-CI confirmation, evidence reports, monthly repair metrics, onboarding help | Yes (onboarding is a service) |
| **Team / Enterprise** | Pro across several repositories, plus RBAC, audit retention, central policy configuration, SSO, compliance reporting, a dashboard | No; built only when a signed customer requires it |

## Recommended pricing model

**Cost structure, from the code.** Diagnosis is one GitHub API read plus a regex pass over at
most 12,000 characters of log: effectively free. A repair attempt runs the customer's verify
commands at the base commit and with the patch, plus the configured regression and quality
gates before and after, plus one model call if `--provider-cmd` is used. That compute runs on
the customer's runner, and the model call uses the customer's key. So today the vendor's
marginal cost per failure is near zero; the real cost is **human time**: onboarding, writing
`verify.yml`, reviewing escalations and the monthly report. Model cost per repair is not yet
measured (see Missing capabilities, item 2).

**Recommended unit: per repository per month, flat.**

- It matches how the ICP thinks (one repository, one CI) and how the audit is already sold.
- Per-failure pricing would charge most when CI is worst, and earn less as the product works.
  It also makes the bill unpredictable for the buyer.
- Per-repair usage pricing only makes sense once the vendor pays for compute or model calls,
  which is the hosted option, postponed. The attempt ceiling (10 per failure) already bounds
  that cost when it arrives.

**Prices to test** (hypotheses, anchored on the published audit price and the original brief's
US$199–499 range; no billing code, payment by invoice or payment link):

| Package | Price to test | Notes |
| --- | --- | --- |
| Starter | Free when self-run (MIT). Paid form: the CI Reliability Audit, US$149 pilot for the first 3 clients, then US$199 per repository | The free Action is distribution, not revenue |
| Pro | US$199 per repository per month, 3-month pilot, first month includes `verify.yml` setup | Raise towards US$499 if pilots show weekly use; drop the setup if onboarding becomes self-serve |
| Team / Enterprise | Quote only | No offer until a customer needs multi-repository, RBAC or SSO in writing |

## Demo strategy

1. **Two-minute proof:** `python examples/demo-repo/run_demo.py`. A real bug, a red pytest
   run, a diagnosis, a verified one-line fix, a branch and an evidence report, offline. Record
   it once as a terminal screencast for the README and outreach.
2. **The fake-fix moment:** run the same failure with a patch that deletes the failing test and
   show `POLICY_REJECTED` next to a green test run. This is the one-sentence pitch made
   visible, and the main message for teams using AI assistants. Not scripted yet: it needs one
   extra patch file in `examples/demo-repo/` and a test that pins the `POLICY_REJECTED` result.
3. **Breadth:** `actions-doctor demo --all` for the six failure types and why each escalates.
4. **On their repository:** the sample audit report, then a free diagnosis of one of their
   recent public failed runs.

Never present the demo as a success rate: it is one bug in one repository.

## Distribution strategy

- **The GitHub repository and the Action** are the storefront. Tag a release, then list the
  Action on the GitHub Marketplace.
- **One technical article:** "An AI can make your CI green by deleting the test", with the
  fake-fix demo. Post it where Python and DevOps engineers read (Show HN, r/Python,
  r/devops, Python Weekly).
- **Public red CI as a lead source:** small Python SaaS and open-source projects with frequent
  failed runs are visible on GitHub. Run the read-only audit on their public history and send
  the top three findings with an offer, not a cold pitch.
- **No paid ads** until a pilot converts; the ICP is reached one repository at a time.

## First 10 customer strategy

1. **Customers 1–3: audit pilots at US$149.** Find 30 public repositories in the ICP with a
   failure rate above 15% over 30 days; send each a short finding from their own history.
   Deliver in 3 business days, hand-reviewed, as `ci-reliability-audit.md` promises.
2. **Convert audits to Pro pilots.** Each audit ends with the one failure class worth fixing
   first; offer a 3-month Pro pilot to set up `verify.yml` and verify the next repairs.
3. **Customers 4–10: teams already using AI coding tools**, reached through the article and the
   fake-fix demo. Lead with Pro; the audit is the low-risk entry for hesitant buyers.
4. **For every customer:** a monthly `fix-repo-metrics` review, a written case study (with
   permission) using measured numbers only, and a list of what they asked for that does not
   exist. The postponed list changes only from that list.

## Success metrics

Product metrics, all produced by `fix-repo-metrics` from stored run artifacts (model cost is
reported as not instrumented until it is):

| Metric | Definition | Target to test |
| --- | --- | --- |
| Time to diagnosis | From the failed run being received to a classification with evidence | Under 1 minute |
| Classified rate | Failures not classified `unknown`, out of all ingested | Above 70% on ICP repositories |
| Verified repair rate | Repairs reaching `VERIFIED_FIXED`, out of attempted repairs | Measured, no target until 20 repairs exist |
| False-fix catches | Green fixes rejected, regressing or not fixing the failure, out of green fixes | Reported per customer; every catch is a sales story |
| Escalation rate | Runs sent to a person, out of all runs | Tracked; a falling rate must not come from weaker policy |
| Attempts per failure | Mean attempts used | Below 3 |

Business metrics: audits sold; audit → Pro conversion (target to test: 1 in 3); Pro pilots
renewed after 3 months; repositories running the Action weekly; time spent per customer on
onboarding and reviews (the real cost).

## 30-day engineering roadmap

Small changes, each with tests, in this order:

| Week | Work | Why |
| --- | --- | --- |
| 1 | Tag `v1.2.0`; pin the Action to it; update `pyproject.toml` description to the product | Customers can install a fixed version |
| 1 | Add the fake-fix patch and its test to the demo; record both runs | Distribution needs a two-minute proof |
| 2 | Report provider token usage and cost when the provider CLI prints it; keep `null` otherwise | Pricing needs measured cost |
| 2 | Post the evidence report summary as a PR comment from `fix-repo-apply --open-pr` | Reviewers see the evidence where they decide |
| 3 | Optional container runner for verify commands (Docker, opt-in) | Closes the largest safety gap for customer code |
| 3 | Slack or email webhook for escalations | Escalations should not wait for someone to look |
| 4 | Fixes and onboarding docs from the first pilots | Real feedback beats planned features |

## Features explicitly postponed

Postponed until a paying ICP customer asks for it and the Diagnose → Verify loop has measured
value. Triggers for each are in [COMMERCIAL_ARCHITECTURE.md](COMMERCIAL_ARCHITECTURE.md#6-what-not-to-build-yet).

- Full Kubernetes or container execution platform
- Hosted, multi-tenant control plane
- Custom billing system (use invoices or a payment link)
- Advanced RBAC and enterprise SSO
- Analytics warehouse and an elaborate dashboard
- Integrations with many CI providers (GitLab first, and only after two qualified prospects)
- Self-hosted enterprise edition (it already runs locally; an edition is packaging and support)
- Automatic merging of any kind: not postponed but excluded

# Initial customer profile (ICP)

Date: 2026-10-05. Inputs: the code as it stands (see [productization-audit.md](productization-audit.md#0-commercialization-update-2026-10-05)),
the existing read-only audit offer ([ci-reliability-audit.md](ci-reliability-audit.md)) and the two
real repositories the tools have been run on. There are no paying customers yet, so every score
below is a judgment with its reason written next to it, not a measurement.

## 1. What the product can serve today

The fit criterion is scored against these facts, not against the roadmap:

| Capability | Scope today |
|---|---|
| Diagnosis from logs (`actions-doctor analyze`, the GitHub Action) | GitHub Actions only. Regex classifier, any language, confidence labelled heuristic. |
| Fix verification (`fix-repo`) | Any git repository and any verify command. Test-level evidence (exact rerun of the failing tests, test-count and skip comparison, coverage) is parsed from **pytest and coverage.py output only**. |
| Writing to a repository (`fix-repo-apply`) | New branch, optional push, optional draft PR. Never merges. |
| Real CI confirmation (`fix-repo-verify-ci`) | GitHub Actions adapter, tested against recorded API responses, not yet against the live API. |
| Multi-repository operation | None on the canonical path (one repository per command). |
| Accounts, RBAC, SSO, hosted service | None. |

## 2. Segment scoring

Scale 1 (poor) to 5 (strong). For **onboarding**, 5 means *easy* to onboard, so every column
points the same way and the total is a plain sum.

| Segment | Pain | Failure frequency | Willingness to pay | Ease of reach | Onboarding | Need for auditability | Fit today | Total |
|---|---|---|---|---|---|---|---|---|
| Solo developers | 2 | 2 | 1 | 4 | 5 | 1 | 3 | 18 |
| **Small SaaS teams (3–30 engineers, Python, GitHub Actions)** | 4 | 4 | 3 | 3 | 4 | 3 | 5 | **26** |
| DevOps / platform teams (larger orgs) | 4 | 5 | 4 | 2 | 2 | 4 | 2 | 23 |
| AI engineering teams (coding agents open PRs) | 4 | 4 | 4 | 3 | 3 | 4 | 3 | 25 |
| Agencies managing many repositories | 3 | 4 | 3 | 3 | 3 | 2 | 2 | 20 |
| Regulated engineering organizations | 3 | 4 | 5 | 1 | 1 | 5 | 1 | 20 |

Reasons per segment:

- **Solo developers.** A red build costs them minutes, not a team's afternoon, and they rarely pay
  for CI tooling. Easy to reach on GitHub and forums and easy to onboard (one Action), so they
  are a good **free-tier and feedback** audience, not the paying customer.
- **Small SaaS teams.** Red builds block several people at once and flaky tests get rerun instead
  of fixed; this is the pain the existing audit offer was written for, and both real runs of the
  tools (this repository and a 957-run private project) look like this segment. They pay for
  developer tools on a card without procurement, onboard with one workflow file, and the Python
  verification path covers their stack. Auditability matters to them as "why is this fix safe to
  merge", not as compliance. Reach is moderate: they have to be found one repository at a time.
- **DevOps / platform teams.** Highest failure volume and budget, but they need many repositories,
  several CI providers, several languages, central policy and RBAC. None of that exists, so the
  fit is low today. They are the expansion segment once multi-repository support exists.
- **AI engineering teams.** Their agents produce many CI-fixing patches, and the most
  differentiated capability here (rejecting fixes that delete, skip or weaken tests, and
  `VERIFIED_FIXED` versus `CI_GREEN_BUT_UNVERIFIED`) addresses exactly their risk. They score
  close to the ICP. The fit is lower because their agents run inside their own platforms, so
  integration means an API or agent hook (not built), and their stacks are often not pytest-only.
- **Agencies.** The many-repository use case is real, but the product has no multi-repository
  view, and agencies resell effort, so automated repair competes with billable hours.
- **Regulated organizations.** They need the audit trail most and would pay most, but they also
  need SSO, retention, signed or tamper-evident evidence (the foundation audit is
  append-oriented, not cryptographically tamper-proof), procurement and security review. Not
  reachable or serviceable by a single-maintainer product today.

## 3. Initial ICP

**Small SaaS engineering teams (3–30 engineers) whose main CI is GitHub Actions and whose main
test suite is pytest.**

Who buys: the engineering lead or the most senior engineer who ends up owning CI ("the person
who gets pinged when main is red"). Budget: a monthly developer-tool line, card payment.

Trigger moments:

1. Main is red often enough that people rerun instead of reading logs.
2. The team has started letting an AI assistant or agent propose CI fixes and wants a check that
   the fix is real before merging.
3. A reviewer approved a "fix" that turned out to skip or delete a test.

Disqualifiers for the first customers (say no politely): no GitHub Actions; no automated tests;
a test suite that is not pytest (diagnosis works, verification evidence will be incomplete);
a requirement for SSO, RBAC or a hosted dashboard; a request for automatic merging.

**Messaging sub-segment, not a second ICP:** teams in the ICP who already use AI coding tools.
The "an AI can make CI green by deleting tests" message lands hardest with them, and it is
what the verification layer was built to catch.

## 4. Product promise for this ICP

> When a GitHub Actions run fails, CI Doctor points to the log lines that explain the failure and
> classifies it. Given a candidate fix (yours, a teammate's or an AI assistant's), it reproduces
> the failure, re-runs the failing tests and your regression checks in a disposable worktree,
> rejects fixes that only turn CI green by weakening the tests, and writes one evidence report
> that says whether the change is safe to merge and why.

The measurable workflow improvements this promise commits to (instrumented, not yet measured on
customers; see [COMMERCIALIZATION_PLAN.md](COMMERCIALIZATION_PLAN.md#success-metrics)):

- **Time to diagnosis**: from the failed run to a diagnosis with the evidence lines.
- **False-fix rate**: fixes that make CI green but are rejected, regress or don't fix the
  original failure, out of all green fixes. The product's job is to catch these before merge.
- **Verified repair rate**: repairs that reach `VERIFIED_FIXED`, out of attempted repairs.

What the promise deliberately does not say: that it fixes CI by itself (a patch comes from a
person, a provider CLI or a recorded file), that diagnosis is always right (confidence is
heuristic), or that anything merges without a person.

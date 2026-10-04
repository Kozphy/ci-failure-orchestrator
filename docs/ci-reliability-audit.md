# GitHub CI Reliability Audit

**Stop rerunning CI. Know why it failed, what it costs, and what to fix first.**

A fixed-price, read-only review of one repository's GitHub Actions history. You get a written report in 3 business days.

| | |
|---|---|
| Price | **US$149** pilot (first 3 clients), then US$199 |
| Scope | One repository, the last 30 days of GitHub Actions runs |
| Access | Read-only (see below). No code changes, no pushes, no merges |
| Delivery | Markdown + PDF report, plus a 20-minute walkthrough call on request |

## What you get

- **Executive summary**: failure rate, rerun rate, estimated wasted minutes, and the one thing to fix first.
- **Failure taxonomy**: failures grouped by cause (test, lint/type, dependency, network/infra, timeout, config), with links to the exact runs.
- **Flaky-test indicators**: commits that failed and then passed with no code change.
- **Cost and runtime waste**: duplicate push + pull_request runs, superseded rerun attempts, cancelled jobs, Windows/macOS minute multipliers.
- **Risk ranking and fixes**: each finding with severity, effort and the evidence behind it.
- **Quick wins and a 30-day roadmap.**

See a [sample report](sample-audit-report.md) generated from this project's own public CI history.

## How it works

1. You book and share read-only access.
2. The collector pulls runs, jobs and failed-job logs through the GitHub REST API. Only one scrubbed error line per failure is kept. Full logs, code and secrets are never stored.
3. The report is generated from that data, then reviewed by hand: every finding is checked against the linked runs before delivery.
4. You receive the report within 3 business days of access being granted.

## Access needed

Pick one:

- A **fine-grained personal access token** scoped to the one repository, with **Actions: Read-only** and **Metadata: Read-only**. Set it to expire in 7 days and revoke it after delivery.
- Or invite the auditor as a **read** collaborator on the repository for the audit period.

Public repositories need no access at all.

## What this is not

- Not a code review or security audit.
- No changes are made to your repository. Implementing the fixes is a separate, optional engagement.
- Minute figures are estimates from job timestamps, not your billing statement. Failure categories come from a pattern classifier and are spot-checked, not guaranteed.

## Book

**[Request an audit](https://github.com/Kozphy/ci-failure-orchestrator/issues/new?title=CI%20Reliability%20Audit%20request&body=Repository%3A%20%0ATeam%20size%3A%20%0AMain%20CI%20pain%3A%20)**: open an issue with the repository name, team size and your main CI pain. Don't post tokens or private details in the issue; access is arranged privately after you book.

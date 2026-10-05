# Commercial architecture

Date: 2026-10-05. This maps the product a customer buys (Diagnose, Fix, Verify) onto code that
exists today. It adds no new architecture; every box below names the module that implements
it. Status words: **supported** (works end to end and is tested), **partial** (works with a
stated limit), **manual** (a person does this step with a provided command), **unsupported**
(does not exist).

## 1. Pipeline

```text
CI Provider                 GitHub Actions (workflow_run trigger, REST API)
    ↓
Failure Ingestion           github_client, service/ingest.py, ci_audit/collect.py, --log-file
    ↓
Classifier                  foundation/classifier.py (regex rules, heuristic confidence)
    ↓
Diagnosis                   doctor/diagnose.py (evidence lines, failing step, next-step playbook)
    ↓
Proposal Engine             service/proposals.py: patch file | provider CLI | recorded patch
    ↓
Sandbox                     disposable git worktrees (service/run.py, patch_sandbox.py)
    ↓
Evaluation                  foundation/evaluator.py (fail-closed technical PASS/FAIL)
    ↓
Regression Verification     service/verification.py (exact rerun, regression suite, gates, invariants)
    ↓
Policy Gate                 foundation/policy.py (POL rules, default ESCALATE) + foundation/remediation.py
    ↓
Human Approval              foundation-decide (recorded, local)
    ↓
PR                          service/apply.py: new branch, optional push, draft PR via gh
    ↓
Audit Evidence              foundation/durable.py (events.jsonl), service/evidence_report.py
```

## 2. The three planes

| Plane | Responsibility | Modules | Rule |
|---|---|---|---|
| **Control plane** | Decides. Classification, planning, retry budget, technical evaluation, policy, remediation state, escalation, human decision. | `foundation/` (classifier, planner, evaluator, retry, policy, remediation, escalation, human_decision, state_machine) | Deterministic. A model can propose; it never decides. Default outcome is ESCALATE. |
| **Execution plane** | Runs things. Verify commands, provider CLIs, git worktrees, the apply step. | `service/run.py`, `service/verification.py`, `service/proposals.py`, `provider_adapters.py` (sandbox runner), `patch_sandbox.py`, `service/apply.py` | `shell=False`, environment allowlists, timeouts. Writes only to temporary worktrees, except `fix-repo-apply`, which writes a new branch. |
| **Evidence plane** | Remembers and explains. Append-only events, evidence files, verification records, the customer evidence report, metrics. | `foundation/durable.py`, `foundation/persistence.py`, `foundation/observability/`, `service/records.py`, `service/evidence_report.py`, `service/remediation_metrics.py` | Sanitized on write. Metrics never authorize a decision. Evidence that wasn't collected never counts as a pass. |

Everything runs on the customer's machine or GitHub runner. There is no hosted control plane,
so there is no tenant data to hold. That is a deliberate first-release property, not a gap to
close quickly (see section 6).

## 3. Minimum sellable workflow: what exists

| Step | Status | How it works today | Limit stated to the customer |
|---|---|---|---|
| GitHub repository connected | supported (diagnosis) / manual (fix) | Diagnosis: add the `CI Doctor` Action workflow (`actions: read`). Fix: run the CLI in a local clone. | No GitHub App; no hosted connection. |
| CI pipeline fails | supported | `workflow_run` trigger on the named workflow. | GitHub Actions only. |
| Failure ingested | supported | Jobs, steps and failed-job logs through the REST API, or a saved log file. Logs are redacted. | |
| Failure classified | supported | Regex classifier with step-name refinement. | Confidence is heuristic, not calibrated. |
| Root-cause diagnosis | partial | Failing job, step, log line range, failing command, failure class, next-step sentence. | A hypothesis from log evidence, not causal analysis. Says `unknown` when no rule matches. |
| Fix proposal created | manual / partial | A patch file, or any CLI provider (`--provider-cmd "claude -p"`) run in a sandbox with an env allowlist. | No built-in model; the customer brings the patch or the provider. |
| Fix executed in isolated environment | supported | Disposable git worktree at the verified base commit. | Process isolation is the worktree plus `shell=False` and env allowlists, not a container. |
| Relevant tests executed | supported (pytest) | Failing tests re-run exactly before and after; mapped affected tests. | Test-level parsing is pytest and coverage.py only. |
| Regression checks executed | supported (configured) | Regression suite, lint, type, security, build gates and invariants from `verify.yml`, before and after. | Only what the customer configures; unconfigured gates are missing evidence, not passes. |
| Policy gate evaluates risk | supported | POL rules, diff risk scoring, verification-integrity analysis (deleted, skipped or weakened tests). | |
| Human approval if required | manual | `ci-orchestrator foundation-decide <run> --action APPROVE --reviewer <name>`. | No notification channel and no approval UI. |
| Pull request generated | supported | `fix-repo-apply --push --open-pr`: new branch through a temporary index, draft PR via `gh`. Never merges. | Needs `gh` for the PR; otherwise prints the command. |
| Verification evidence produced | supported | `fix-repo/evidence-report.json` and `.md` per run, refreshed at each stage. | |
| Real CI confirms the fix | partial | `fix-repo-verify-ci` reads the CI run for the pushed commit. | GitHub adapter tested against recorded responses, not the live API. |
| Audit report stored | supported (local) | `runs/<id>/` with `events.jsonl`; `foundation-verify` checks consistency. | Local files; append-oriented, not cryptographically tamper-proof; no retention service. |

## 4. Product modes mapped to capabilities

The modes are packaging over one engine. Nothing is disabled to create them; each mode is the
set of commands a customer is told to use.

| Mode | Customer receives | Commands and modules | Writes |
|---|---|---|---|
| **Diagnose** | Failure class, root-cause hypothesis with log evidence, affected job and step, recommended next step, `diagnosis.json`; optionally a 30-day reliability report. | `actions-doctor diagnose` (alias of `analyze`), the GitHub Action, `ci-audit-collect` / `ci-audit-report` | Nothing (job summary and an optional local file). |
| **Fix** | Diagnose plus: a candidate patch (patch file or provider), verification in a disposable worktree, test results, a branch or draft PR. | `ci-orchestrator fix-repo`, `fix-repo-apply` | Temporary worktrees; a new branch and draft PR only after approval. |
| **Verify** | Fix plus: regression and quality-gate comparison, verification-integrity analysis, diff risk, policy decision, remediation state (`VERIFIED_FIXED` vs `CI_GREEN_BUT_UNVERIFIED`), real-CI confirmation, evidence report, repair metrics. | `fix-repo --verification-config verify.yml`, `fix-repo-verify-ci`, `fix-repo-report`, `fix-repo-metrics`, `foundation-verify` | Same as Fix. |

Policy, retry budget and escalation run in every mode that touches code. They are not a Verify
upsell: selling a Fix tier without the policy gate would sell the unsafe version of the product.

## 5. Safety boundaries

Listed with code references and tests in [SAFETY_CONTROLS.md](SAFETY_CONTROLS.md). Summary:
read-only diagnosis; no write to the target repository except a new branch after approval;
never merges; default ESCALATE; finite retries (at most 10 attempts); allowlisted
environments; redaction on every write; timeouts on every external call; `fix-repo-apply
--dry-run`; rollback commands in every apply result. Known gaps (no container isolation, no
command allowlist, no cost budget, no tamper-evident log) are listed there too.

## 6. What not to build yet

Each item is postponed until a paying customer in the ICP ([ICP.md](ICP.md)) asks for it and the
Diagnose → Verify loop has measured value.

| Postponed | Why not now | What would trigger it |
|---|---|---|
| Hosted control plane / multi-tenant SaaS | Running customer code or holding logs means a security program, data processing terms and on-call. The local model avoids all of it. | Customers who cannot run the CLI or Action themselves. |
| Kubernetes or container execution platform | Worktrees on the customer's runner are enough for pytest repos. | Untrusted provider code that needs stronger isolation than a worktree. |
| GitHub App | The Action covers diagnosis with the repository's own token. | Customers with many repositories, or a need for interactive commands. |
| Custom billing system | Use a payment link and license keys until usage-based pricing is validated. | More than about 20 paying accounts. |
| RBAC, SSO, audit retention service | Single-team customers use GitHub permissions. | The first team or enterprise deal that requires them in writing. |
| Dashboard / analytics warehouse | The Markdown evidence report and `fix-repo-metrics` JSON answer the same questions. | Customers asking for cross-repository trends. |
| More CI providers (GitLab, CircleCI, Jenkins) | The `CIProvider` interface exists; each adapter needs real API testing. | Two or more qualified prospects on the same provider. |
| Self-hosted enterprise edition | It already runs locally; an "edition" is packaging and support, not code. | A regulated customer with a signed pilot. |
| More languages for test-level evidence | Each runner needs a parser and fixtures. | ICP customers whose second suite is Jest or Go. |

The experimental modules (`module_status.EXPERIMENTAL`: tournaments, fleet, canary, production
proof, distributed runtime and others) are not part of any product mode and are not sold.

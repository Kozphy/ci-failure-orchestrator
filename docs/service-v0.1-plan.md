# Service v0.1.0 plan — narrow GitHub CI failure service

**Status:** reviewed plan; Stages 0, 1 and 1b implemented (see [CHANGELOG](../CHANGELOG.md)); Stage 2 next. Nothing is deleted before its stage is reviewed.  
**Baseline (2026-09-25, commit `4620583`):** 382 tests pass; 17 workflows; ~90 top-level modules plus `foundation/` and `governed/`.

This document records the architecture audit, the canonical module set, the staged plan with acceptance tests, and the decisions taken during review. Every stage must end with the full test suite green and report concrete evidence (test names, commands, artifacts), not feature claims.

---

## 1. Primary user journey (target)

1. Receive a failed GitHub Actions workflow (reusable Action first, GitHub App later, or explicit CLI).
2. Retrieve workflow metadata and failed-job logs.
3. Sanitize secrets and untrusted log content.
4. Classify the likely root cause with evidence references.
5. Reproduce the failure in a disposable git worktree.
6. Accept a patch from a provider interface.
7. Apply the patch only inside a fresh disposable worktree.
8. Run allowlisted verification commands from trusted configuration.
9. Enforce finite retries and fail-closed policy.
10. If approved, create a new branch and a **draft** PR; never write to the default branch.
11. Escalate sensitive files, auth, CI configuration, environment/dependency failures, and uncertain results.
12. Record structured metrics and an append-only audit trail.

Constraints: preserve foundation invariants; one canonical path; no graph database (small in-memory DAG only); LLM providers behind an interface with deterministic checks authoritative; no production claims from fixtures or synthetic benchmarks; never expose tokens, secret-bearing prompts, or complete unredacted logs; never auto-merge.

---

## 2. Audit — duplicate execution paths

| # | Path | Entry | Overlaps |
| --- | --- | --- | --- |
| 1 | **Foundation + fix-repo** | `foundation-*`, `fix-repo`, `fix-repo-apply` | reference path (canonical) |
| 2 | Governed pipeline | `governed/*`; CLI `run`, `benchmark`, `explain`, `replay` | own state machine, policy, retry, sandbox, SQLite store |
| 3 | Trust gateway | `trust_gateway.py`, `trust_policy.py`, `trust.py`, `network_discovery.py`; CLI `trust-run` | policy + state machine |
| 4 | Supervisor repair loop | `supervisor.py`, `repair_state_machine.py`, `github_repair_adapter.py`, `task_idempotency.py` | state machine, GitHub ingest, policy |
| 5 | Delivery control plane | `control_plane*.py`, `api.py`, `policy.py`, `tournament.py`, `production.py` | policy, evaluation |
| 6 | Scripted repair loop | `repair.py`, `repair_loop.py`, `repair_planner.py`, `agent_loop.py`, `agent_executor.py`, `command_agent.py`, `repair_agents.py` | proposal + retry |
| 7 | Second patch-execution stack | `repair_execution.py`, `execution.py`, `worktree.py`, `workspace.py`, `test_runner.py`, `git_validation.py` | `patch_sandbox.py` (three worktree implementations) |
| 8 | Runtime queue | `autonomous_runtime.py`, `distributed_runtime.py`, `runtime_contracts.py` | orchestration |
| 9 | `self-heal.yml` | `scripts/sandbox_repair.py`, `scripts/self_heal_github.py` | real GitHub path that commits and opens draft PRs **without foundation policy/escalation** |
| 10 | `agent-issue-delivery.yml` | issue label → `bash -lc "$CI_REPAIR_AGENT_CMD"` | issue body reaches the agent (prompt-injection surface); non-draft PR |
| 11 | `auto-merge-after-checks.yml` | `check_suite` / `status` | **auto-merges PRs — violates the no-auto-merge constraint** |

Below the path level: three classifiers, four policy engines, four state machines, three GitHub ingest modules, two test-selection modules, and ~25 research/production/benchmark modules used only by scripts and their own tests.

### Gaps found in code against the journey

| Gap | Where | Stage |
| --- | --- | --- |
| Policy ignores failure classification: a dependency failure "fixed" by a small source patch is auto-APPROVED | `foundation/policy.py` (`_evaluate` never reads `classification`) | 3 |
| No escalation on low classifier confidence | `foundation/policy.py` | 3 |
| `fix-repo-apply --open-pr` does not pass `--draft`; branch name is not checked against `main`/`master`/default branch | `service/apply.py` | 2 |
| `--provider-env GITHUB_TOKEN` would pass a token to the provider | `service/proposals.py` | 2 |
| Symlink (`120000`) and submodule entries in patches are not rejected | `patch_sandbox.py` | 2 |
| Log sanitization redacts secrets only: no ANSI/control stripping, no `::workflow-command::` neutralization, no untrusted-data framing in prompts | `foundation/sanitization.py`, `service/prompt.py` | 2 |
| Evidence strings, not log line-range references | `foundation/classifier.py` | 2/4 |
| Verify commands must come from trusted config in an Action context (never from the checked-out repo) | new | 2/6 |
| No run schema; no time-to-diagnosis or cost metrics | new | 5 |
| No DAG over workflow jobs / packages / tests (`graph.py` is tied to the diagnosis `Stage` model) | new | 4 |
| `repo_fix.py` exceeds 1,000 lines | `repo_fix.py` | 1 (done) |
| `foundation/persistence.py` (1,254) and `foundation/runner.py` (1,082) exceed 1,000 lines | foundation | 1b (done) |

---

## 3. Canonical set

Machine-readable source of truth: `ci_failure_orchestrator/module_status.py` (enforced by `tests/test_module_boundaries.py`). Human view: [module-status.md](module-status.md).

- **Canonical:** `foundation/**`, `service/**` (Stage 1), `repo_fix.py` (compatibility shim), `patch_sandbox.py`, `provider_adapters.py`, `github_client.py`.
- **Entrypoint:** `cli.py` (may wire experimental stacks; experimental commands are labeled in `--help`).
- **Experimental:** everything else, grouped (diagnosis, governed, trust, supervisor, control-plane, scripted-repair, execution-stack, runtime, evidence/research, merge-conflict, memory, telemetry). Not deleted or moved in v0.1.0.

Rule: a canonical module must not import an experimental module.

---

## 4. Staged plan and acceptance tests

| Stage | Scope | Acceptance (all stages: full suite green) |
| --- | --- | --- |
| **0** | Module-status manifest; import-boundary test; experimental CLI labels; auto-merge disabled; `self-heal` and `agent-issue-delivery` manual-only | `tests/test_module_boundaries.py`; `tests/test_workflow_safety.py`; `tests/test_cli_groups.py` |
| **1** | Split `repo_fix.py` into `service/` (pure move); `repo_fix.py` re-exports | `tests/test_repo_fix.py` unchanged and passing; no canonical file > 1,000 lines |
| **1b** | Split `foundation/persistence.py` and `foundation/runner.py` (verbatim move; both stay as stable import paths) | AST of every moved definition identical to HEAD; full suite green; no canonical file > 1,000 lines |
| **2** | Security boundaries: symlink/submodule/binary/traversal patches rejected; seeded token absent from every artifact, prompt, run record, PR body; token env names blocked for provider and verify; workflow-command and ANSI neutralization; untrusted-log framing; trusted verify allowlist; refuse default-branch targets; draft-only PRs; static no-merge check | `tests/test_security_boundaries.py` |
| **3** | Policy: escalate dependency / infrastructure / network / unknown classifications and low confidence; environment-failure detection at reproduce time escalates without calling the provider | dependency failure + source-only patch → `AWAITING_HUMAN`; golden baseline diff shown before intentional update |
| **4** | `service/dag.py`: workflow `needs`, declared packages, test→module imports; upstream-most failed job; affected tests as evidence; undeclared import → dependency classification | cycle rejection, upstream selection, affected tests, undeclared-package tests |
| **5** | `schemas/run.v1.json`; `run.json` per run; `service-metrics`: classification accuracy and false approval (labeled runs only), repair success, time-to-diagnosis p50/p95, retries, estimated cost (labeled as estimate) | schema validation; metric tests on known inputs; population + "not production evidence" in output |
| **6** | GitHub integration phase 1: reusable composite Action (see §5.1); draft PR or escalation summary/issue; replace `self-heal.yml` with a dogfood caller | static `action.yml` test (minimal permissions, no `pull_request_target`, `--draft`, no merge); apply-refusal tests |
| **7** | Local end-to-end demo: three local repos (repair, dependency escalation, sensitive block), local bare remote, recorded provider by default | `tests/test_demo.py`: APPROVED / AWAITING_HUMAN / REJECTED-or-BLOCKED |
| **8** | Three real repository case studies (see §5.2) with provider comparison (see §5.3) | per case: `run.json`, audit events, PR/issue link, sanitized log excerpt, reproduction commands; labeled n=1 |
| **9** | Simplified CI (`ci.yml`, `security.yml`, dogfood caller; others manual-only or removed after review); `docs/branch-protection.md`; `CHANGELOG.md`; `docs/release-checklist-v0.1.0.md`; README split into Implemented / Experimental / Planned; delete workflows retired in Stage 6 | docs present; workflow static tests; release checklist items checked with evidence |

---

## 5. Review decisions

### 5.1 GitHub integration — hybrid, phased

**Phase 1 (v0.1.0): reusable composite Action**, triggered by `workflow_run` (`conclusion == failure`) in the caller repository.

- Security: no server, no app private key. Uses the caller's `GITHUB_TOKEN` with `contents: write`, `pull-requests: write`, `actions: read` only in the job that opens the draft PR; the diagnosis/repair job runs with read-only permissions and without credentials in the checked-out failed revision (`persist-credentials: false`). Never `pull_request_target`. Provider secrets are passed only to the provider step via an explicit env allowlist.
- Trusted config: verify-command allowlist, provider command and policy overrides come from action inputs in the caller's default-branch workflow file, never from the failed revision.
- Maintainability: one `action.yml` + a documented caller workflow; no hosted infrastructure.
- Developer experience: copy one caller workflow, set one repository variable for the provider command.

**Phase 2 (after v0.1.0): GitHub App** for broader events (check runs, re-requests, comment commands), multi-repo installation and fine-grained permissions.

- Security: app private key held only by the webhook service (secret manager, never in repositories or logs); short-lived installation tokens per job; webhook signature verification (`X-Hub-Signature-256`) required; least-privilege app permissions (`actions: read`, `checks: read`, `contents: write` on non-default refs via branch protection, `pull_requests: write`, `issues: write`).
- Scalability: the webhook service enqueues jobs that call the same canonical `service` entrypoint as the Action, so both integrations share one execution path, schema and audit trail.
- Status in v0.1.0: **planned** (design doc only).

### 5.2 Case studies — three sources

| Case | Required outcome | Source | Why |
| --- | --- | --- | --- |
| (a) | Successful code repair → draft PR | New small public repo under the owner's account with a seeded failure, running real Actions | Controlled and reproducible |
| (b) | Environment/dependency failure correctly escalated | Historical failure from a public OSS repository, reproduced at the failing commit | Authentic real-world failure |
| (c) | Sensitive change correctly blocked | One of the owner's existing repositories | Familiar environment, practical applicability |

Each case records: repository and commit, failing run URL (when on GitHub), sanitized log excerpt, reproduction commands, verify allowlist, provider(s), `run.json`, audit timeline, PR or escalation link, and a comparison note. Every case is labeled **single case study (n=1), not production evidence**. Secrets: provider keys only via local environment or repository secrets; nothing stored in case-study artifacts (checked by the Stage 2 artifact scan). Mapping confirmed in review.

### 5.3 Providers for the successful-repair case — comparison with a human baseline

Run case (a) with each available provider CLI behind the same `ProposalSource` interface — Claude Code (`claude -p`), Codex CLI, Cursor Agent CLI — plus a recorded hand-written patch as the reproducibility baseline. Deterministic checks (worktree verification + policy) stay authoritative for every provider.

Recorded per provider: outcome, attempts, verification result, files changed, diff size, time-to-first-valid-patch, estimated cost, and whether the patch matches the human baseline's intent. Providers run in an empty temp directory with an env allowlist; their own tool permissions are documented per CLI. Results are comparative anecdotes (n=1 per provider), not a benchmark.

### 5.4 Versioning — decided: dual track

The package stays at `1.2.0` in `pyproject.toml` (lowering it would make pip treat the release as a downgrade). The service release is tagged `service-v0.1.0`, then `service-v0.2.0`, …. `CHANGELOG.md` documents both tracks (package: semantic `1.x`; service: `service-v0.x`).

### 5.5 Risky workflows — phased

- **Stage 0:** `auto-merge-after-checks.yml` → manual trigger only **and** job hard-disabled (`if: false`), so it cannot merge even when dispatched. `self-heal.yml` and `agent-issue-delivery.yml` → `workflow_dispatch` only. Their jobs depend on `workflow_run` / `issues` event payloads, so a manual dispatch is a no-op until they are replaced.
- **Stage 6:** replace `self-heal.yml` with the canonical Action caller.
- **Stage 9:** delete workflows no longer needed; record each change in `CHANGELOG.md`.

# Current-state assessment (Phase 0)

**As of 2026-10-04** · `main` at `fa29384` plus the uncommitted GitHub Action work (`action.yml`, `doctor/action.py`).
Replaces the 2026-09-22 version, which predated `doctor`, `ci_audit`, `fix-repo` and the Action.

Scope: what exists today, what is missing for a multi-repository CI reliability control plane, and what must not be rewritten. No production code was changed to produce this document.

**Evidence labels used below**

- **verified**: the cited lines were read and the behaviour confirmed during this assessment.
- **measured**: produced by running a command in this repository (command given).
- **inferred**: follows from the code structure, but no test demonstrates it.

Every number in this document was measured. Nothing here is a production claim: there are no production deployments, and no data from real multi-repository traffic.

---

## 1. Summary

The repository is a **single-process Python library with a CLI**: about 15k lines of canonical code plus about 10k lines of experimental code. It has two real capabilities:

1. **Diagnose** a failed GitHub Actions run (`actions-doctor analyze`, and the composite Action).
2. **Repair one repository locally under governance** (`ci-orchestrator fix-repo`, then `fix-repo-apply`). This step reproduces the failure in a git worktree, asks an external coding agent for a patch, verifies the patch in a fresh worktree, runs a policy check, and writes an auditable run directory. The only write to the repository goes to a new branch or a draft PR.

The governance core (`foundation/`) has sound bones: fail-closed defaults, a retry budget, an append-only event log and a benchmark harness. It is still a **single-repository, single-run, operator-invoked tool**. It has no incident model, no ingestion service, no multi-repo routing, no canary, no versioned policy or classifier, and no correlation IDs. The sandbox has no isolation beyond a git worktree and an environment allowlist.

Its biggest liability is **duplication**. Alongside the canonical stack sit 82 experimental modules with their own parallel state machines, policy engines, retry budgets and stores. The ADRs, threat model and SLO documents describe those experimental stacks, not the code that actually runs.

---

## 2. Component diagram (current)

```text
                       ┌──────────────────────────── entry points ────────────────────────────┐
                       │ actions-doctor analyze|demo   composite Action (action.yml)          │
                       │ ci-orchestrator fix-repo | fix-repo-task | fix-repo-apply            │
                       │ ci-orchestrator foundation-run|inspect|events|resume|verify|decide|  │
                       │                 benchmark|operations-report|slo-check                │
                       │ ci-orchestrator ci-audit-collect | ci-audit-report                   │
                       └──────┬───────────────┬────────────────┬──────────────────┬───────────┘
                              │               │                │                  │
                       ┌──────▼─────┐  ┌──────▼──────┐  ┌──────▼───────┐  ┌───────▼───────┐
                       │ doctor/    │  │ service/    │  │ foundation/  │  │ ci_audit/     │
                       │ diagnose,  │  │ fix-repo    │  │ state machine│  │ run/job       │
                       │ render,    │  │ orchestration│ │ classifier   │  │ collection +  │
                       │ action     │  │ prompt, patch│ │ policy, retry│  │ report        │
                       └──┬─────┬───┘  │ checks, apply│ │ sandbox(stub)│  └───────┬───────┘
                          │     │      └──┬───┬───┬──┘  │ evaluation   │          │
                          │     │         │   │   │     │ durable store│          │
                          │     │         │   │   └─────►  audit/metrics│          │
                          │     │         │   │         └──────────────┘          │
                          │     │         │   │                                   │
                  ┌───────▼──┐  │   ┌─────▼─┐ └───────────┐                       │
                  │classifier│  │   │patch_ │             │                       │
                  │(regex)   │  │   │sandbox│      ┌──────▼──────────┐            │
                  └──────────┘  │   │git    │      │provider_adapters│            │
                                │   │worktree│     │(external agent  │            │
                                │   └───────┘      │ subprocess)     │            │
                                │                  └─────────────────┘            │
                          ┌─────▼──────────────────────────────────────────────────▼──┐
                          │ github_client (urllib, single page, no retry/backoff)      │
                          └────────────────────────────────────────────────────────────┘

 Persistence: files only, under artifacts/<run_id>/ (state.json, events.jsonl, metadata.json,
              escalation/*, decision.json, metrics). No database, queue or server.

 Adjacent and NOT on the canonical path (82 modules, experimental per module_status.py):
   governed/ (SQLite store, own policy/retry/state machine), trust/, supervisor, fleet, canary,
   slo, dashboard, platform, task_idempotency (SQLite leases), legacy diagnosis/rank/replay.
   cli.py imports governed/trust at the top level, so they are loaded but unused by the
   canonical commands.
```

**Measured size** (`module_status.CANONICAL` vs `EXPERIMENTAL`, by line count):

- Canonical: 11 entries, 14,927 lines.
- Experimental: 82 entries, 10,089 lines.
- `cli.py` alone: 834 lines.

`tests/test_module_boundaries.py` stops canonical modules from importing experimental ones. This is the main thing keeping the two worlds apart.

---

## 3. Request and job flows

### 3.1 `fix-repo` (the real repair path)

Implemented in `service/run.py:158-323`.

```text
operator CLI ──► resolve repo + base commit ──► reproduce failure at base (verify command)
   │                                                 │ passes → stop, "nothing to fix"
   │                                                 │ environment failure → escalate
   │                                                 │   (no state.json written)
   ▼
foundation runner (FailureEvent → classify → retry loop):
   RepoFixProposalFactory ──► prompt (untrusted logs fenced) ──► external agent subprocess
        ──► extract unified diff ──► structural patch checks (patches.py:131-161)
        ──► WorktreeSandbox: fresh git worktree, git apply, run verify commands (timeout 600 s)
        ──► EvaluationResult (fail-closed) ──► PolicyEngine POL-001…015 ──► RetryBudget
   ▼
terminal state: APPROVED | REJECTED | AWAITING_HUMAN | ESCALATION_ERROR | FAILED
   ▼
artifacts/<run_id>/ (state.json, events.jsonl, metadata.json with patch sha256, escalation packet)
   ▼
fix-repo-apply (separate, operator-invoked): status == APPROVED, patch hash matches
metadata.json, target is not a protected branch, temporary index, new branch or draft PR only.
```

### 3.2 `foundation-run` (simulation)

This flow uses the same runner as 3.1, with a synthetic sandbox. `foundation/sandbox.py:82-88` writes a marker file instead of applying the patch, verification is a stub (`:94-113`), and the default proposal is a placeholder comment (`foundation/proposal_factories.py:74-77`). It exercises the control flow and the benchmark, but it **does not repair anything** (verified).

### 3.3 `actions-doctor analyze` and the composite Action

```text
run id or saved log ──► github_client (jobs page 1, logs) ──► classifier ──► diagnosis with
quoted evidence lines and a policy *preview* ──► text/JSON
Action: neutralize(workflow commands) ──► job summary (fenced) + outputs failure-class,
diagnosis-file. Permissions: actions:read, contents:read. Never mutates.
```

### 3.4 `ci-audit-collect` / `ci-audit-report`

These commands read recent runs and jobs of one repository through `github_client` and write a local report. They are read-only.

---

## 4. Inspection inventory (the 15 Phase 0 questions)

| # | Question | Finding |
| --- | --- | --- |
| 1 | Current architecture | A library plus CLI with one process per invocation, and file-based state per run. See §2. |
| 2 | Entry points | Two console scripts (`ci-orchestrator`, `actions-doctor`) and the composite Action. `api.py` is an in-memory class: there is **no HTTP server, webhook receiver or worker**. |
| 3 | CI integrations | GitHub Actions only, through REST using `urllib`. `collect_run` reads a single page, so at most 100 jobs per run. No retry, backoff or rate-limit handling, and log reads are unbounded. The set of conclusions counted as "failed" differs between `doctor` and `ci_audit`. |
| 4 | Retry | `foundation/retry.py:45-69`: max 3 attempts; stop after 2 identical failures, 1 identical proposal (exact sha256), or 2 attempts with no progress. Not aware of cost, wall-clock time or failure class. **Defeated by the placeholder proposal**: it embeds the attempt number, so identical proposals never hash equal (inferred from `proposal_factories.py:74-77`). |
| 5 | Classification | Regex rules in `classifier`. Confidence is a constant (0.9 on a match, 0.35 for unknown), not calibrated. No classifier version is recorded. No LLM is in the classification path. |
| 6 | Persistence | `state.json` uses atomic writes. `events.jsonl` is fsynced with a monotonic sequence number. There are **no locks**, duplicate event IDs are detected only within one process, and there is no hash chain. Escalation artifacts and the metrics summary use non-atomic writes. `resume_run` only appends a marker event. |
| 7 | Evaluation | Fail-closed `EvaluationResult`, but the default `TestRunnerTool` stub passes. The real evaluation happens only in `WorktreeSandbox` (fix-repo). The benchmark has 38 cases; the baseline holds 26. |
| 8 | Policy | `foundation/policy.py`, rules POL-001…015, default ESCALATE, and an engine error escalates (POL-013). It has defects (§7) and no policy version. |
| 9 | Logging / audit | About 30 counters behind a label allowlist. Structured events go to `events.jsonl`. No correlation or trace IDs, no structured logs, no OpenTelemetry exporter. Audit evidence is unsigned, and `metadata.json` sits in the same writable directory as the run artifacts it describes. |
| 10 | Tests | 75 test modules and 592 collected tests, with no skips and no network. Approximate counts per area: foundation 158, service 50, doctor 35, ci_audit 18, meta and safety 15, governed 11, trust 24, legacy 182 (measured with `pytest --collect-only -q`). |
| 11 | Deployment | None: no Dockerfile, no PyPI release, no git tags, no service. The only runtime besides a local CLI is the composite Action. |
| 12 | Security boundaries | See §7.2. Untrusted log text is fenced and neutralized. The patch structure is checked. Apply is gated. The sandbox is weak: no network or resource isolation, credential directories can be read, and `.git` is shared. |
| 13 | ADRs | ADR 0001–0007 are all "Accepted" but describe the **governed** stack. For example, 0003 covers a SQLite governed store and 0004/0006 cover EvalForge and a `RETRY` policy outcome. None of them describes foundation, fix-repo, apply or the Action. |
| 14 | Technical debt | Duplicate engines, stale docs, over-claiming text, the full test suite run five times per PR, and decorative workflows (§8). |
| 15 | Do not rewrite | §10. |

---

## 5. Strengths (keep and build on)

1. **Separation of decisions.** Evaluation PASS, policy APPROVE and mutation are three different steps, and the default outcome is ESCALATE. Only `fix-repo-apply` writes, and only to a new branch or a draft PR.
2. **Real verification on the repair path.** `patch_sandbox` runs `git worktree add` and `git apply` and re-runs the operator's verify command against the base commit (`service/run.py`, `patch_sandbox.py`).
3. **Fail-closed policy with explicit rule IDs**, including escalation for low confidence (POL-015), dependency files (POL-007) and CI workflow edits (POL-004).
4. **Structural patch checks before any worktree is created**: symlinks, submodules, binaries, `..`, `.git` and secret patterns are rejected (`service/patches.py:131-161`, `service/adapters.py:118-127`).
5. **Untrusted-input handling**: logs are fenced with a fence longer than any backtick run in them, workflow commands are neutralized, and annotations are escaped (`service/untrusted.py`, `doctor/action.py`).
6. **Append-only, sequenced event log** and atomic state writes, so a run is reconstructable.
7. **Workflow safety tests**: write-scoped workflows must stay inert, and `pull_request_target` is banned (`tests/test_workflow_safety.py`). Module-boundary tests keep canonical code free of experimental imports.
8. **A benchmark harness with a reviewed baseline** (`foundation-benchmark`, 38 cases, compare mode).
9. **Small dependency footprint**: standard-library HTTP, no framework.

---

## 6. Missing production capabilities, by target lifecycle stage

The target lifecycle runs: **ingest → incident → classify → propose → policy → sandbox → evaluate → retry → canary → merge/escalate → audit → SLO**.

| Stage | Status | Evidence |
| --- | --- | --- |
| Multi-repo ingestion (webhook or poller, dedup, rate limits) | **Absent** | No server. `FailureEvent.from_dict` generates new `event_id` and `run_id` on every call (`foundation/models.py:66-105`), so redelivered events cannot be deduplicated. |
| Incident model (incident ID, correlation ID, lifecycle timestamps, resolved_at) | **Absent** | `FailureEvent` has optional repository, SHA and branch only. Incidents are not tracked across runs. |
| Taxonomy and metrics (per-class precision, confusion matrix) | **Partial** | 16 classification benchmark cases. The class labels exist, but there is no confusion-matrix output and no calibration. |
| RepairProposal contract (risk, blast radius, rollback, versions) | **Partial** | Proposals carry patch, files and a hash. No risk estimate, rollback plan, or generator/model version. |
| Policy with ALLOW_WITH_CANARY and REQUIRE_HUMAN_APPROVAL | **Partial** | The outcomes are APPROVE, REJECT and ESCALATE. There is no canary outcome and no policy version. |
| Sandbox isolation (network, resources, credentials, process group, deadline) | **Weak** | Worktree plus environment allowlist only. `HOME`, `USERPROFILE`, `APPDATA` and `LOCALAPPDATA` pass through (`service/common.py`). No process-group kill, no overall run deadline, no upper bound on `--max-attempts`. |
| Evaluation beyond "verify command passes" (flaky reruns, targeted tests) | **Partial** | A single verify run, with no rerun for flakiness. |
| Retry budget aware of cost, time and failure class | **Partial** | Counts only (§4.4). |
| Canary (draft PR plus observed CI on the branch) | **Absent** on the canonical path | `canary.py` is experimental, in memory and used only by tests. |
| Escalation packet (who, why, evidence, decision deadline) | **Partial** | A packet is written. `reviewer_id` defaults to `"human"`, `decision.json` is overwritten, and there is no deadline or timeout. |
| Audit evidence (tamper-evident, versioned inputs and outputs) | **Partial** | Hashes exist but are unkeyed and stored next to the data they cover. No hash chain on the canonical path. No input/output hashes per step. |
| SLI/SLO computed from real runs | **Absent** | `config/slo.json` holds 5 `EXAMPLE_TARGET` entries. `slo-check` reads metrics files, not real traffic. |
| Dashboard | **Absent** on the canonical path | `dashboard.py` is experimental. |
| Chaos / fault injection | **Partial** | Faults can be injected into the sandbox and evaluator only. Nothing covers GitHub API failures, crashes partway through a write, or concurrent runs. |
| Observability (correlation IDs, structured logs, traces) | **Absent** | Counters only. |

---

## 7. Architectural risks and verified defects

### 7.1 Correctness defects (verified, each a small fix)

1. **Persistence failure is reported as success.** On `PersistenceError` the runner never sets `workflow_status` to `PERSISTENCE_ERROR` (`foundation/runner.py:579-590`), so `persistence_ok` is always true (`recorder.py:112`, `aggregator.py:133`).
2. **Reclassification reuses the same event** (`foundation/runner.py:655-665`). The second classification sees the same input as the first, so reclassifying cannot change the outcome.
3. **Policy rule IDs are misattributed.** The escalation path is tagged POL-003 (`foundation/policy.py:579-582`) and the infra path is tagged as broad scope (`:608-611`). POL-001 is unreachable.
4. **The restricted-tool check is a no-op** (`foundation/policy.py:662-664`).
5. **Protected paths are matched by substring** (`foundation/policy.py:674`). `a/.github-notes/x` matches `.github`, and a path can avoid a substring that a stricter matcher would catch.
6. **A failed or timed-out provider's stdout is still parsed for a patch** (`service/adapters.py:49-52`). That patch then passes through structural checks and verification (`:112-133`), so this is a fail-open gap, not a bypass.
7. **`clean_after_apply` is inverted** (`patch_sandbox.py:191`).
8. **A benchmark metric is overwritten**: `escalation_accuracy` is reassigned at `foundation/benchmark/metrics.py:147`.
9. **The simulated sandbox reports success without applying anything** (`foundation/sandbox.py:82-88`, `:94-113`). The timeout is checked only after the work finishes (`:115-116`).

### 7.2 Security risks

- **The sandbox can read credential files** through the passed-through home and profile environment variables.
- **The worktree shares the primary repository's `.git`**, so a verify command could write hooks or config there (inferred).
- **There is no command allowlist.** The operator's argv is split with `shlex` and executed.
- **Run IDs are not validated before being used in filesystem paths** in the apply and inspect commands (inferred).
- **`metadata.json` is the only proof of the patch hash at apply time**, and it is unsigned and stored in the writable run directory.
- **Redaction (`sanitize_text`) misses** `github_pat_` tokens, JWTs, Slack and npm tokens, GCP keys and AWS secret access keys.
- **`git push` in apply uses ambient credentials.** There is no scoped token.
- **Workflows:**
  - `live-semantic-merge-eval` exposes `OPENAI_API_KEY` to every step of the job.
  - `foundation-benchmark` has no `permissions:` block.
  - Actions are pinned by tag, not by SHA.
  - CodeQL runs with `upload: never`, so findings are not surfaced.

### 7.3 Structural risks

- **Duplicate engines.** Across the package (canonical and experimental) there are 6 retry budgets, 6 state machines, 7 policy engines, 6 durable stores, 7+ evaluators, 4 hash chains and 10 percentile helpers, and `RepairPlan` is defined 5 times. A reader cannot tell which engine is authoritative without `module_status.py`.
- **Documentation describes the wrong system.** The ADRs, `threat-model.md`, `slo.md` vs `sli-slo.md`, and `target-architecture.md` all describe experimental modules. Readers and reviewers draw conclusions about code that does not run.
- **No lint or type gate on canonical code.** `ci.yml` runs ruff and mypy only on the trust modules.

---

## 8. Unnecessary complexity already present

| Item | Why it is complexity without value today |
| --- | --- |
| 65 experimental modules unreachable from any CLI command (AST import scan) | Code that is maintained and tested but never executed by users. |
| `cli.py` imports governed/trust at the top level | Slower startup, larger blast radius for import errors, and a blurred boundary. |
| Full test suite run on every PR by five workflows: `ci`, `ct`, `production-proof`, `repair-execution`, `promotion` (verified by grep) | Five times the CI minutes for the same signal. |
| `promotion.yml` "canary" and "production" jobs | They only write JSON. The names imply a deployment that does not exist. |
| `production-proof.yml` gates on an example metrics file | Proves that a fixture exists, not that production works. |
| Inert write-scoped workflows (`agent-issue-delivery`, `self-heal`, `auto-merge-after-checks`) | Safe, because the tests enforce that they stay inert, but they add surface and confusion. |
| Over-claiming docs (`pyproject.toml` description, `AUTONOMOUS-RUNTIME.md`, `SUPERVISOR-CONTROL-PLANE.md`, `OBSERVABILITY.md`, "tamper-evident" in `production-evidence.md`) | Claims the code cannot back. Fixing them costs only text. |

---

## 9. Staff-level gaps

These are the gaps a reviewer would notice. They are listed by leverage, not by effort.

1. **There is no single authoritative design record.** The ADRs need to describe foundation, fix-repo, apply and the Action, and say which stacks are frozen.
2. **There is no incident abstraction.** Everything is a "run". Multi-repo work, deduplication, MTTR and SLOs all depend on an incident with an ID, a correlation ID and lifecycle timestamps.
3. **Versions are not part of the evidence.** A decision cannot be reproduced later without the policy, classifier, prompt and model versions that produced it.
4. **The threat model is not derived from the real trust boundaries**: untrusted logs, the external agent, the verify command, the apply credentials and the Action token.
5. **SLOs are not tied to measurement.** The targets are examples, and nothing computes SLIs from real runs.
6. **Failure modes of the orchestrator itself are untested**: GitHub API errors, crashes partway through a write, concurrent runs on one repository, and stale locks.
7. **Simulation is not separated from reality in naming and reporting.** `foundation-run` success can be confused with a real repair.

---

## 10. Do not rewrite (extend in place)

| Keep | Why |
| --- | --- |
| `foundation/state_machine.py` | A small, explicit transition table. Add states by extending it, not by replacing it. |
| `foundation/policy.py` and its fail-closed defaults | Fix the defects in §7.1 and add versions and outcomes, but keep the engine. |
| `foundation/retry.py` | Add time and class awareness as extra stop reasons. |
| Durable `state.json` + `events.jsonl` | Add locks, a hash chain and versions. Do not introduce a database until multi-repo concurrency requires one, and then use SQLite (already a dependency of Python). |
| `service/` fix-repo flow and `patch_sandbox` worktree verification | This is the only path that really verifies a repair. Harden it rather than replacing it. |
| `fix-repo-apply` safeguards | Keep the draft-PR-only and hash-check design. Add signing and a scoped token. |
| `service/untrusted.py` and the `doctor` neutralize/fence handling | Correct, and covered by hostile-input tests. |
| `tests/test_module_boundaries.py`, `tests/test_workflow_safety.py` | These keep the canonical path honest. |
| `foundation-benchmark` and its reviewed baseline | The evaluation spine for every later phase. |
| `doctor/` and the composite Action | The product surface that people actually use. |

The experimental stacks should be **frozen, not deleted**. Deleting them needs the review called for by the standing constraint ("Do not delete or rewrite existing work until the proposed consolidation is reviewed").

---

## 11. Proposed order of next changes (each the size of one PR)

Smallest changes first. None of them needs Kubernetes, Kafka, Redis, microservices, a vector DB or another language.

1. **Phase 1a: fix the verified defects in §7.1**, each with a regression test that fails on today's code. No new features.
2. **Phase 1b: domain model.** Add `incident_id`, `correlation_id`, `detected_at` and `resolved_at`, plus policy, classifier and prompt versions, to the event and state schema as a `foundation.v2` schema that can still read v1. Make `FailureEvent` identity deterministic from repository, run ID and attempt, so duplicates are detectable.
3. **Phase 14 (early): correct the ADRs.** Supersede ADR 0003, 0004 and 0006 with records that describe foundation as it is, and add ADRs only where a decision is actually being made.
4. **Phase 15 (early): rewrite the threat model** from the boundaries in §7.2.
5. **Then multi-repo ingestion** (Phase 2): a poller or webhook built on the standard library, with a SQLite incident ledger for deduplication and locking, behind an ADR.

Phases 4 to 13 (proposal contract, policy outcomes, sandbox hardening, canary as draft PR plus observed branch CI, escalation, audit, SLIs, dashboard, chaos) build on 1b. Each phase will report measured evidence, not targets.

---

## 12. Stale documents to correct or mark superseded

- `docs/adr/0001…0007`: they describe the governed stack.
- `docs/threat-model.md`: it does not cover fix-repo, the provider, apply, the Action or tokens.
- `docs/slo.md` vs `docs/sli-slo.md`: they disagree about which stack is measured.
- `docs/architecture/target-architecture.md`: its boxes map to experimental modules.
- `OBSERVABILITY.md`, `AUTONOMOUS-RUNTIME.md`, `SUPERVISOR-CONTROL-PLANE.md`, `production-evidence.md`, and the `pyproject.toml` description: they claim more than the code does.

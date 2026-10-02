# Agent control plane roadmap — gap analysis and adoption decisions

**Status:** reviewed 2026-09-25. Phase 1 adopted and implemented as Stage 2b; the rest is scheduled or deferred as recorded below. The v0.1.0 service plan stays authoritative for what ships: [service-v0.1-plan.md](service-v0.1-plan.md).

The roadmap does not replace CI repair. Its aim is to make the existing repair loop more reliable, resumable, safe, auditable and measurable, and able to host more than one agent later. Its own closing principle applies here too: a component is added only when a concrete requirement justifies it.

---

## 1. Roadmap in brief

| Roadmap item | Intent |
| --- | --- |
| Task / Run / Attempt | Separate the objective (task) from each execution (run) and each proposal (attempt) |
| Durable state | Survive crashes; resume from the last good step (files first, SQLite → PostgreSQL later) |
| Sandbox / worktree | Every attempt in a disposable copy; the primary checkout is never touched |
| Retry budget with cost | Finite attempts, identical-failure limits, and a token / money limit |
| Evaluation-driven repair | Deterministic checks decide; the agent only proposes |
| EvalForge integration | External evaluation layer comparing agents on the same failure |
| Policy engine | Separate *capability* (what an agent can do) from *authority* (what it may do) |
| Multiple agents | `AgentAdapter` interface; Codex, Claude, OpenCode, … behind it |
| Deterministic router | Choose an agent per task from recorded results, not from an LLM |
| Control plane vs control panel | Build the execution/governance plane first; a UI panel is optional and later |
| Phases 1–11 | Phase 1: Task / Run / Attempt wrapping the existing flow; later phases add the items above |
| Alternative directions (§17) | A: CI reliability platform · B: AI governance platform · C: agent evaluation platform · D: full agent control plane |

---

## 2. Gap analysis against the code

| Roadmap component | Existing code | Gap |
| --- | --- | --- |
| **Task** | `service/records.py` (`Task`, `TaskStore`; Stage 2b) | Done: `tasks/<id>/task.json`, append-only `runs.jsonl`, `fix-repo --task-id`, `fix-repo-task` |
| **Run** | `foundation/durable.py` `DurableRunState` (`state.json`), `FileAuditStore` (`events.jsonl`), `FileEvidenceStore` | None for v0.1.0. Run ↔ task link lives in `runs.jsonl` and `metadata.json`, so the durable run schema is unchanged |
| **Attempt** | `foundation/retry.py` `AttemptRecord` (retry view) + `service/records.py` `Attempt` (service view, `attempt-NNN.json`) | Done: agent identity, status, patch hash and timing per attempt |
| **Durable state / resume** | `foundation/recovery.py` `resume_run` | `resume_run` only assesses consistency and emits `RUN_RESUMED`; it does not re-execute. Continuing a run from its last attempt is **deferred** |
| **Database** | Files only (atomic writes, append-only JSONL) | SQLite / PostgreSQL **deferred**; not needed at current volume |
| **Sandbox** | `patch_sandbox.py` `WorktreePatchVerifier`; `service/adapters.py` `WorktreeSandbox` | None. Stage 2 added the structural patch guard before any worktree |
| **Retry budget** | `RetryBudget` (`max_attempts`, identical failure / proposal limits, no-progress limit) | No cost or token field → **Stage 5** cost budget |
| **Evaluation-driven repair** | `foundation/evaluator.py` `LocalEvaluator`; verification commands decide `technical_status` | None. Evaluation PASS ≠ policy APPROVE ≠ workspace mutation stays a foundation invariant |
| **Policy (authority)** | `foundation/policy.py` `StaticPolicyEngine` (defaults to ESCALATE); classification- and confidence-aware since Stage 3 | None for v0.1.0 |
| **Capability limits** | Provider env allowlist and credential denylist (`service/common.py`), empty temp cwd, timeout, output cap (`provider_adapters.py`) | Each CLI's own tool permissions are documented per case study (Stage 8), not enforced here |
| **Human approval** | `foundation/human_decision.py` (`foundation-decide`); `fix-repo-apply` requires durable `APPROVED` | None |
| **Audit** | `events.jsonl` with sequence numbers; `foundation-verify` | None |
| **Multiple agents** | `ProposalSource` protocol (`PatchFileSource`, `ProviderCommandSource`): any CLI, one per run | One agent per run. Comparison happens across runs of one task (Stage 8). Several agents within one run **deferred** |
| **Router** | Experimental `agent_router.py` (not on the canonical path) | **Deferred**: a deterministic router needs recorded per-agent results first, which Stage 5 metrics and Stage 8 comparisons produce |
| **EvalForge** | None | **Deferred** until after v0.1.0; `attempt-NNN.json` + `run.json` (Stage 5) are the intended export format |
| **Metrics** | `foundation/observability/slo.py`; `foundation-operations-report`, `foundation-slo-check` | Run schema, time-to-diagnosis, estimated cost per run / task / agent → **Stage 5** |
| **Control panel** | None | **Deferred**; CLI + JSON artifacts are the interface for v0.1.0 |

---

## 3. Adoption decisions

1. **Phase 1 now** — Task / Run / Attempt records wrapping the existing flow, before Stage 3. Implemented as Stage 2b; evidence in [CHANGELOG](../CHANGELOG.md).
2. **Stage 5 enriched** — the run schema carries `task_id` and per-attempt `agent`; an optional cost budget (estimated provider cost / tokens per run) is checked before each attempt and its exhaustion escalates, never approves.
3. **Deferred until after v0.1.0** — real resume continuation, EvalForge integration, deterministic router, control panel, SQLite / PostgreSQL. Reason: stability of the v0.1.0 path first.
4. **Kept open** — alternative directions A–D remain options if requirements or constraints change. The current plan already leans on A (failure taxonomy, retries, time-to-diagnosis) and B (policy, evidence, approval, audit, redaction); C becomes possible once Stage 8 provider comparisons exist; D is the largest scope and stays a later decision.

---

## 4. Cautions

- **No new top-level tree.** The roadmap's proposed layout (`control_plane/`, `domain/`, `agents/`, `routing/`, `sandbox/`, `policy/`, `budget/`, …) would duplicate `foundation/` and `service/` and add a twelfth overlapping path to the audit in the service plan (§2). New concepts go into `service/` (or `foundation/` when they are invariants) until a requirement forces a split.
- **Name collision.** `control_plane.py` and `control_plane_run.py` already exist as experimental modules; a canonical `control_plane/` package would shadow `control_plane.py` on import. Pick another name if a package is ever needed.
- **Router needs data.** Routing by measured success rate, latency and cost is only meaningful after per-agent results are recorded across real tasks.
- **Cost is an estimate.** Provider CLIs report tokens and cost inconsistently or not at all; any cost figure or budget must be labeled as estimated and must not be used as the only stop condition.
- **No production claims.** Fixtures, synthetic benchmarks and single case studies are labeled as such (n=1, not production evidence).

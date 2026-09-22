# Current-state architecture

Staff audit of `ci-failure-orchestrator` (package version 1.2.x) before the governed-agent upgrade.

This document describes **what exists today**. It does not claim production SLOs or measured fleet reliability.

---

## 1. Current architecture

The repository is a **Python library + CLI** (`ci-orchestrator`) that implements a policy-first CI reliability control plane. It is organized as loosely coupled modules rather than a single process pipeline.

```text
┌─────────────────────────────────────────────────────────────┐
│ CLI (classify / rank / analyze / analyze-run / trust-run)   │
└───────────────┬─────────────────────────────┬───────────────┘
                │                             │
     Diagnosis stack                Trust / repair stacks
                │                             │
  GitHub ingest → classify →        Supervisor + AgentTask
  graph/rank/causal → verify plan   RepairCoordinator + ledger
                │                   Agent loop / tournament
                │                   TrustToolGateway
                ▼                             ▼
         HashChainedAuditLog          SQLite stores + evidence
```

**Approximate inventory:** ~87 package modules, ~53 test modules, 15 GitHub Actions workflows, narrative docs under `docs/` (no numbered ADRs).

**Parallel “eras” of APIs (important):**

| Stack | Role | Entry |
| --- | --- | --- |
| Diagnosis / RCA | Normalize jobs/logs, classify, rank root causes | CLI `analyze`, `analyze-run` |
| Supervisor repair | Bounded authority + `RepairIncident` state machine | Library (`repair_state_machine`, `supervisor`) |
| Planner / agent loop | `RepairPlan` → execute → evaluate → escalate | Library (`repair_planner`, `agent_loop`) |
| Trust gateway | Structured tool proposals + policy + sandbox | CLI `trust-run` |
| Distributed runtime | Queue + eval gate + DLQ + SLO snapshot | Library (`distributed_runtime`) |

There is **no single CLI command** that runs ingest → classify → plan → tool → sandbox → evaluate → policy → escalate end-to-end.

---

## 2. Current execution flow

### 2.1 Diagnosis (CLI-backed)

```text
GitHub jobs + logs
  → github_ingest / FailedCheck normalization
  → classifier.classify_error  (regex taxonomy)
  → PipelineGraph + RootCauseRanker + causal edges
  → verification.plan_verification
  → optional HashChainedAuditLog append
```

### 2.2 Bounded autonomous repair (library)

```text
FailedCheck
  → classify_failed_check + supervisor.evaluate_repair
  → AgentTask (+ idempotency_key)
  → RepairCoordinator.plan / deliver_idempotent
  → WorkerResult
  → VerificationResult (independent gates)
  → GREEN | REVIEW_REQUIRED | RERUNNING | DENIED | ESCALATED
```

### 2.3 Trust control plane (CLI `trust-run`)

```text
Structured RepairProposal
  → TrustPolicyEngine (config/policies.yaml)
  → approval / IsolatedWorkspace sandbox
  → evaluate / verify
  → audit events
```

---

## 3. Existing strengths

- **Policy-first design:** supervisor authorities, forbidden actions, trust allow/deny/require-approval.
- **Independent verification:** repair success is not agent self-report (`VerificationResult.successful`).
- **Idempotent delivery:** `SQLiteCompletionLedger` + `IdempotentTaskDeliverer` with concurrent/crash tests.
- **Tamper-evident audit:** hash-chained JSONL with secret redaction.
- **Durable local state:** SQLite run store, incident memory, completion ledger.
- **Sandbox primitives:** worktree / isolated workspace / patch sandbox.
- **Benchmarks & research fixtures:** corpora under `benchmark/`, scripts under `scripts/`.
- **Retry / AI budgets:** multiple retry budget shapes; `InvocationBudget` on durable runs.
- **Provider-neutral routing:** agent router + tournament selection (safety as hard gate).

---

## 4. Missing capabilities (vs target governed pipeline)

| Capability | Status |
| --- | --- |
| Unified event → … → metrics pipeline | **MISSING** (composition left to callers) |
| Dedicated context-engineering layer (budget, prioritization, sanitization as one subsystem) | **PARTIAL** (`memory_context`, trust context; no token budget builder) |
| Single canonical domain model set | **PARTIAL** (many overlapping dataclasses) |
| Typed tool registry with schemas + risk levels | **PARTIAL** (trust proposals; no registry abstraction) |
| MCP-ready tool boundary / docs | **MISSING** |
| EvalForge client adapter + integration doc | **PARTIAL** (`EvaluationGate` protocol only) |
| Explicit full-lifecycle state machine (RECEIVED…SUCCEEDED) | **PARTIAL** (`RepairState`, gateway states; not unified) |
| Human escalation as structured actionable artifact | **PARTIAL** (gates exist; evidence packaging uneven) |
| Declarative policy engine for repair proposals (files/tools/eval) | **PARTIAL** (supervisor + trust YAML; not one engine) |
| Threat model / SLO / runbook docs as specified | **MISSING** or narrative-only |
| Numbered ADRs | **MISSING** |
| Portfolio-facing explain/replay CLI | **PARTIAL** (`analyze`; no `explain`/`replay` run UX) |

---

## 5. Risky coupling

1. CLI, supervisor loop, agent loop, trust gateway, and platform APIs are **loosely coupled libraries** with divergent success predicates naming.
2. GitHub Actions workflows and scripts assume compositions that are not enforced by one orchestrator type.
3. Optional extras (`openai`, `observability`) sit beside stdlib-first paths — easy to document as “always on.”

---

## 6. Duplicated logic

| Concept | Duplicates |
| --- | --- |
| `RepairPlan` | `repair_planner.py`, `repair.py`, `control_plane_run.py` |
| `EvaluationResult` | `agent_loop.py`, `control_plane_run.py`, `trust_gateway.py` |
| `RetryBudget` | `evaluator.py`, `supervisor.py`, `trust_gateway.py` |
| Failure taxonomy | `classifier.py` vs `github_repair_adapter.classify_failed_check` |
| Tournament / selection | `agent_router.py` vs `tournament.py` |
| Provider registry | `trust.ProviderRegistry` vs `provider_adapters.ProviderRegistry` |
| Isolation | `execution.IsolatedWorkspace`, `worktree.GitWorktreeWorkspace`, patch sandbox |

---

## 7. Persistence / state model

| Store | Module | Purpose |
| --- | --- | --- |
| `SQLiteIncidentStore` | `sqlite_memory.py` | Failure memory incidents |
| `SQLiteRunStore` | `autonomous_runtime.py` | Durable run + leases + DLQ |
| `SQLiteCompletionLedger` | `task_idempotency.py` | Task idempotency claim/complete |

Default local paths under `.ci-orchestrator/`. Designed as replaceable by Postgres + durable queue later (`docs/AUTONOMOUS-RUNTIME.md`).

---

## 8. Audit model

`HashChainedAuditLog` (`audit.py`):

- Append-only JSONL
- Fields: `ts`, `event_id`, `correlation_id`, `event` / `event_type`, redacted `payload`, `prev_hash`, `hash`
- Redacts sensitive keys and bearer/token patterns

Additional chains:

- `RepairIncident` transition digests (SHA-256 over transition payload)
- HMAC-signed evidence helpers (`evidence_signing.py`)

---

## 9. Testing strategy

- Pytest under `tests/` (~53 modules)
- Strong coverage on: repair state machine, idempotency, supervisor, trust gateway, memory/planner, sandbox/worktree, graph/ranker, runtime, benchmarks
- Style: unit + `tmp_path` SQLite; fixtures in `examples/` and `benchmark/`
- Live GitHub generally mocked / optional

Gap: few tests that assert the **entire** target pipeline as one integration path.

---

## 10. Migration risks

| Risk | Mitigation |
| --- | --- |
| Canonicalizing types breaks imports | Add new adapters; keep old types; deprecate gradually |
| New orchestrator duplicates trust gateway | Compose gateway/supervisor rather than rewrite |
| Subpackages omitted from setuptools | Update package discovery when adding packages |
| Over-claiming “production proven” | Docs must separate capability vs measured evidence |
| Expanding MCP/EvalForge without need | Interfaces + docs first; optional adapters only |
| Breaking CLI semantics | Preserve existing commands; add new ones (`run`, `explain`, `replay`) |

---

## Source-of-truth pointers

- Package: `ci_failure_orchestrator/`
- CLI: `ci_failure_orchestrator/cli.py`
- Policy/trust: `supervisor.py`, `trust_gateway.py`, `config/policies.yaml`
- Idempotency: `task_idempotency.py`
- Audit: `audit.py`
- Runtime: `autonomous_runtime.py`, `distributed_runtime.py`
- Docs: `docs/AUTONOMOUS-REPAIR-LOOP.md`, `docs/L45-RELIABILITY-RUNTIME.md`, `docs/trust-control-plane-design.md`

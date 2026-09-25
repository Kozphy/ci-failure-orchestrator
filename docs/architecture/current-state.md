# Current-state architecture

**As of 2026-09-22** · package `ci-failure-orchestrator` 1.2.x  
Source of truth: code + tests + golden suite. See also [repository-audit.md](../repository-audit.md).

This document describes **what exists today**. It does **not** claim production SLOs or E5 production proof.

---

## 1. Architecture overview

The repository is a **Python library + CLI** (`ci-orchestrator`) with **three parallel stacks**. The portfolio-canonical stack is **foundation (Phases 2–13)**.

```text
┌────────────────────────────────────────────────────────────────┐
│ CLI: foundation-* | run/explain/replay/benchmark | analyze |   │
│      trust-run | classify | rank                               │
└────────────┬───────────────────┬───────────────────┬───────────┘
             │                   │                   │
      foundation/          governed/           legacy / adjacent
   Phases 2–13            Deterministic        diagnosis, trust,
   (auditable core)       AgentModel +         supervisor, release
                          dry-run sandbox      predicates, fleet…
```

| Stack | Entry | Character |
| --- | --- | --- |
| **Foundation** | `foundation-run`, `foundation-benchmark`, inspect/verify/resume | Deterministic control plane; scripted/heuristic proposals; local sandbox |
| **Governed** | `run`, `benchmark`, `explain`, `replay` | Parallel composition; dry-run; SQLite store |
| **Diagnosis** | `analyze`, `analyze-run`, `classify`, `rank` | RCA over jobs/logs |
| **Trust** | `trust-run` | Policy YAML + MockLLM gateway (separate from foundation) |
| **Release predicates** | library (`release_gates.py`) | Boolean dataclasses; not foundation terminals |

Foundation does **not** import governed or trust. CLI wires stacks side-by-side.

**Inventory (approx.):** package modules under `ci_failure_orchestrator/`, ~61 test modules, 16 GitHub Actions workflows, numbered ADRs under `docs/adr/0001`–`0007`.

---

## 2. Foundation execution flow

```text
FailureEvent
  → RECEIVED → CONTEXT_READY → CLASSIFIED
  → loop (retry budget):
       PLANNED → EXECUTING → PROPOSAL_READY
       → SANDBOX_RUNNING → EVALUATING → EVALUATED
       if PASS → POLICY_REVIEW
            APPROVE → APPROVED   (no primary-tree apply)
            REJECT  → REJECTED
            ESCALATE → … → AWAITING_HUMAN
                 optional foundation-decide:
                   APPROVE → APPROVED (still no primary apply)
                   REJECT  → REJECTED
                   DEFER / REQUEST_CHANGES → remain AWAITING_HUMAN
       else → RETRY_DECISION → RETRYING | FAILED
  → optional durable artifacts under artifacts/runs/<run_id>/
  → non-authorizing metrics emission
```

**Invariants enforced in code:** finite retries; policy default ≠ APPROVE; evaluation fail-closed without target verification; metrics never authorize; escalation does not auto-decide.

---

## 3. Evaluation & evidence

| Mechanism | Path | Notes |
| --- | --- | --- |
| Phase tests | `tests/test_foundation_phase_*.py` | E2 |
| Golden suite | `benchmarks/foundation/cases/**` (26) | Synthetic, deterministic E3 |
| Baseline gate | `benchmarks/foundation/baselines/current.json` + CI | E3 |
| Sample evidence | `evidence/sample-runs/{01-approve,02-reject,03-escalate,04-human-approve}` | E4-simulated; see `evidence/manifest.json` |
| Provisional SLOs | `config/slo.json` / `foundation/observability` | EXAMPLE_TARGET only |

---

## 4. Strengths (today)

- Explicit state machine with illegal-transition failures.
- Fail-closed deterministic policy gate with category/path rules.
- Finite retry budget with fingerprint / no-progress / security stops.
- Local durable state + append-oriented audit + inspect/verify/resume.
- Human escalation package writer (local files).
- Explicit human decision resume (`foundation-decide`) from `AWAITING_HUMAN` → `APPROVED`/`REJECTED` without primary-tree apply.
- `fix-repo` (`service/`; `repo_fix.py` re-exports it): real patches for another local git repo (patch file or one provider CLI). They are verified by executing the operator's commands in a disposable worktree, with the local failure reproduced first. Every foundation control still applies. `fix-repo-apply` writes a new branch in the target repo only after `APPROVED`.
- Golden synthetic regression harness with baseline compare in CI.
- Observability rebuild that cannot break or authorize the orchestrator.

---

## 5. Explicit non-goals / gaps (today)

| Gap | Status |
| --- | --- |
| Live LLM proposal factory in foundation default path | Not wired in `foundation-run`; opt-in via `fix-repo --provider-cmd` (single provider, no ablation evidence) |
| Policy APPROVE → mutate primary workspace | Deliberately not done |
| Human reviewer decision → resume-to-approve loop | **Partial (M4 slice)** — `apply_reviewer_decision` / `foundation-decide`; still no notification channel |
| Cryptographic integrity of foundation durable audit | Append-oriented only (`audit.py` hash-chain is a separate stack) |
| Single CLI from GitHub ingest → PRODUCTION_SUCCESS | Not unified |
| E5 production evidence | Absent |
| MCP / EvalForge live adapters | Docs / ADR boundary only |

---

## 6. Persistence & audit models

| Store | Module | Notes |
| --- | --- | --- |
| Foundation file artifacts | `foundation/persistence.py` | `state.json`, `events.jsonl`, evidence blobs |
| Hash-chained JSONL | `audit.py` | Used by diagnosis/trust paths; not foundation integrity model |
| Governed SQLite | `governed/store.py` | Parallel stack |
| Incident / ledger SQLite | `sqlite_memory.py`, `task_idempotency.py` | Adjacent repair runtime |

---

## 7. Testing strategy

- Strong phase coverage for foundation 2–10, 12–13 and governed pipeline.
- Trust / diagnosis / repair modules have dedicated tests of varying depth.
- Live GitHub generally mocked or optional.
- CI: `.github/workflows/ci.yml` (pytest), `foundation-benchmark.yml` (golden suite), `security.yml` (CodeQL/Gitleaks).

---

## 8. Risky coupling

1. Multiple policy engines (foundation static rules vs trust YAML vs supervisor authorities).
2. Overlapping success vocabulary (`APPROVED` vs `REPAIR_SUCCESS` / `RELEASE_READY` / `PRODUCTION_SUCCESS`).
3. README historically over-claimed unification — corrected toward M3 honesty; keep docs aligned with this file.

**Resolution:** treat [control-authority-map.md](../control-authority-map.md) as the single map of which stack owns each concern. Foundation wins for portfolio claims.

---

## Source-of-truth pointers

- Foundation: `ci_failure_orchestrator/foundation/`
- CLI: `ci_failure_orchestrator/cli.py`
- Golden cases: `benchmarks/foundation/`
- Sample evidence: `evidence/`
- ADRs: `docs/adr/`
- Audit: `docs/repository-audit.md`
- Control authority: `docs/control-authority-map.md`

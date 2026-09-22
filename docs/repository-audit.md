# Repository Forensic Audit

**Repository:** `Kozphy/ci-failure-orchestrator`  
**Package version:** 1.2.0  
**Audit date:** 2026-09-22  
**Scope:** Implementation + tests + CI + benchmarks + docs claims (no portfolio polish)  
**Method:** Code/tests as source of truth; documentation claims demoted when they conflict.

> **P0 status:** Closed 2026-09-22 (honest public narrative + sample evidence package). Portfolio Steps 9–12 still require user approval.

---

## 0. What this repository actually is

Three parallel stacks coexist under one CLI (`ci-orchestrator`):

| Stack | Package path | Default execution character |
| --- | --- | --- |
| **Foundation (Phases 2–13)** | `ci_failure_orchestrator/foundation/` | Deterministic local control plane: classify → plan → tools → proposal → sandbox → evaluate → retry → policy → escalate → persist → metrics/SLI/SLO → golden benchmarks. Proposals are heuristic or **scripted**; sandbox verification is often **stubbed/scheduled**. |
| **Governed** | `ci_failure_orchestrator/governed/` | Parallel simulation-oriented composition with `DeterministicAgentModel`, dry-run sandbox, SQLite store, 8 synthetic cases. |
| **Legacy / adjacent** | root package modules | Diagnosis (`analyze`), trust gateway (`trust-run`), supervisor/repair SMs, release/production **predicates**, fleet/canary/DORA helpers, research scripts, many GHA workflows. |

**Canonical auditable core for Staff / Governance / Research positioning:** `foundation/` (Phases 2–13).

**What it is not (under default paths):**

- Not a live multi-provider coding agent applying patches to a primary workspace on policy APPROVE.
- Not a single end-to-end ingest → tournament → `PRODUCTION_SUCCESS` CLI product.
- Not production-proven fleet reliability (no E5 evidence).
- Not cryptographically tamper-proof foundation audit (append-oriented durable log; hash-chain lives in older `audit.py`).

---

## 1.1 Implementation Truth Matrix

Values: **Yes** / **Partial** / **No** / **Unknown**.  
“Production-proven” requires real production evidence (E5). Tests alone never imply Yes.

| Capability | Claimed | Implemented | Tested | Measured | Production-proven | Evidence |
|---|---:|---:|---:|---:|---:|---|
| Heuristic CI failure classification | Yes | Yes | Yes | Partial | No | `foundation/classifier.py`; `tests/test_foundation_phases_2_6.py`; BENCH-CLASS-* |
| Bounded sanitized context assembly | Yes | Yes | Yes | No | No | `foundation/context.py`, `sanitization.py` |
| Deterministic tool planning | Yes | Yes | Yes | No | No | `foundation/planner.py`, `tools.py` |
| Path-safe tool execution | Yes | Yes | Yes | Partial | No | `tools.py` (`_safe_relpath`); BENCH-SEC-* |
| Repair proposal generation (LLM) | Partial (docs honest) | Partial | Partial | No | No | Default heuristic / `ScriptedProposalFactory`; governed `DeterministicAgentModel`; no live LLM in foundation default |
| Isolated sandbox (temp copy) | Yes | Yes | Yes | Partial | No | `foundation/sandbox.py`; phase 2–6 + security benches |
| Real patch apply to primary tree | No (docs honest) | No | N/A | No | No | `runner.py`: “Policy APPROVE does not apply the patch to the primary workspace” |
| Independent evaluation gate | Yes | Yes | Yes | Partial | No | `foundation/evaluator.py`; fail-closed without target verification |
| Finite retry budget + stop conditions | Yes | Yes | Yes | Yes (bench) | No | `foundation/retry.py`; `test_foundation_phase_7_retry.py`; BENCH-RETRY-* |
| Deterministic policy gate (APPROVE/REJECT/ESCALATE) | Yes | Yes | Yes | Yes (bench) | No | `foundation/policy.py`; phase 8 tests; BENCH-POLICY-*; fail-closed default ≠ APPROVE |
| Human escalation package | Yes | Yes | Yes | Partial | No | `foundation/escalation.py`; phase 9 tests; writes local artifacts; no reviewer channel/decision loop |
| Durable run state + audit events | Yes | Yes | Yes | Partial | No | `foundation/persistence.py` (append-oriented); phase 10 tests; BENCH-AUDIT-001 |
| Hash-chained tamper-evident audit | Partial (adjacent stack) | Partial | Yes | No | No | Older `audit.py` HashChainedAuditLog; **not** foundation durable log integrity model |
| Observability metrics / SLI / SLO | Yes | Yes | Yes | Yes (local rebuild) | No | `foundation/observability/*`; `config/slo.json`; EXAMPLE_TARGET; metrics never authorize |
| Golden synthetic benchmark harness | Yes | Yes | Yes | Yes | No | `foundation/benchmark/*`; 26 cases; baseline `benchmarks/foundation/baselines/current.json`; CI `foundation-benchmark.yml` |
| Sample durable evidence package | Yes | Yes | Yes (verify CLI) | Yes (sim) | No | `evidence/sample-runs/**`; `evidence/manifest.json` |
| Governed end-to-end CLI pipeline | Yes | Yes | Yes | Partial | No | `governed/pipeline.py`; `cli.py` `run`/`benchmark`; dry-run character |
| Diagnosis RCA (`analyze`) | Yes | Yes | Yes | Partial | No | `classifier`/`ranker`/`graph`/`causal`; examples; pytest modules |
| Trust tool gateway | Yes | Yes | Yes | Partial | No | `trust_gateway.py`, `trust_policy.py`; MockLLM scenarios |
| REPAIR/RELEASE/PRODUCTION success predicates | Yes (library) | Yes | Partial | Partial | No | `release_gates.py` + CI fixtures/examples; **not wired as foundation terminal** |
| Multi-provider tournaments / fleet / canary as default product | No (docs demoted) | Partial | Partial | Partial | No | Library modules + workflows; not `foundation-run` path |
| Live GitHub Actions ingest | Yes | Yes | Partial | No | No | `github_client.py`, `analyze-run`; requires credentials |
| MCP tool boundary | Documented readiness | Partial | No | No | No | ADR 0007 + docs; not a live MCP server in package |
| EvalForge integration | Documented boundary | No | No | No | No | `docs/integrations/evalforge.md` only |
| Unified single control-plane process | No (docs honest) | No | No | No | No | Parallel stacks; foundation/governed provide partial pipelines |

---

## 1.2 Evidence Classification

### Scale

| Level | Definition |
| --- | --- |
| **E0** | Conceptual / docs only |
| **E1** | Implemented in code |
| **E2** | Automated tests verify behavior |
| **E3** | Repeatable evaluation or benchmark |
| **E4** | Observable runtime under realistic workload or controlled simulation with retained artifacts |
| **E5** | Real production evidence |

### Claim → Evidence Level (important claims only)

| Claim | Level | Notes |
| --- | --- | --- |
| Foundation state machine enforces legal transitions | **E2** | `state_machine.py` + phase tests |
| Policy is fail-closed; default cannot be APPROVE | **E2–E3** | `PolicyConfig` validation; BENCH-POLICY-* |
| Retry loops are bounded | **E2–E3** | retry engine + BENCH-RETRY-* |
| Technical PASS ≠ policy APPROVE ≠ primary apply | **E2** | runner docstring + tests; APPROVE does not mutate primary tree |
| Escalation packages written without auto-decision | **E2** | escalation module + phase 9 |
| Durable artifacts reconstructable locally | **E2–E4** | persistence + inspect/verify CLI; sample evidence package |
| Synthetic golden suite passes vs baseline | **E3** | 26 cases; CI workflow; local re-run 2026-09-22: required cases passed |
| SLI/SLO reports rebuild from artifacts | **E2–E3** | observability tests; EXAMPLE_TARGET only |
| Metrics never authorize orchestration | **E2** | `SafeMetricsRecorder`; runner isolation |
| System is production-proven control plane | **E0 — not claimed** | README aligned to M3 after P0 |
| Tamper-evident production proof | **E1–E2 (partial stack)** | hash-chain elsewhere; foundation audit not crypto-integrity |
| Live LLM auto-repair reduces MTTR in production | **Unverified / E0** | Do not publish |

### Evidence inventory (what exists today)

| Artifact class | Location | Status |
| --- | --- | --- |
| Unit/integration tests | `tests/test_foundation_*.py`, `tests/test_governed_pipeline.py`, … (~61 test modules) | Present |
| Foundation golden cases | `benchmarks/foundation/cases/**` (26) | Present, synthetic |
| Foundation baseline | `benchmarks/foundation/baselines/current.json` | Present |
| Governed synthetic cases | `benchmarks/cases/*.json` (8) | Present |
| Example diagnosis fixtures | `examples/github_*.json` | Present |
| Example production metrics | `benchmark/production_metrics.example.json` | Example only |
| Committed runtime evidence package | `evidence/sample-runs/**`, `evidence/manifest.json` | Present (E4-simulated; regenerate via `scripts/generate_sample_evidence.py`) |
| ADRs | `docs/adr/0001`–`0007` | Present |
| Architecture / ops docs | `docs/architecture/*`, `docs/operations/*` | Present; current-state updated 2026-09-22 |

---

## 1.3 Architecture planes (as implemented)

```text
Control plane:   foundation/runner.py + state_machine.py
Policy plane:    foundation/policy.py (+ trust_policy.py in parallel stack)
Execution plane: tools.py + sandbox.py (temp workspace; stub verification available)
Evaluation plane: evaluator.py
Evidence plane:  persistence.py (local) + optional HashChainedAuditLog (legacy)
Observability:   foundation/observability/*  (non-authorizing)
Escalation:      escalation.py → local package → AWAITING_HUMAN
```

Foundation does **not** import governed or trust. CLI wires stacks side-by-side.

---

## 1.4 Doc ↔ implementation discrepancies

| Item | Status after P0 |
| --- | --- |
| README claimed Phases 2–6 only | **Fixed** — README centers Phases 2–13 |
| README claimed production control plane / tamper-evident proof as product | **Fixed** — M3 simulation framing |
| `current-state.md` claimed no ADRs / no end-to-end CLI | **Fixed** — rewritten for three stacks + foundation flow |
| Governed “production-oriented” wording | **Fixed** — simulation-oriented / dry-run |

---

## 1.5 Maturity Assessment (Part XV)

| Level | Definition |
| --- | --- |
| M0 Concept | Idea/design only |
| M1 Prototype | Core path implemented; limited verification |
| M2 Tested System | Important behavior covered by automated tests |
| M3 Evaluated System | Repeatable benchmarks/experiments exist |
| M4 Operationally Demonstrated | Realistic workloads + observability + controlled failure evidence retained |
| M5 Production Proven | Real production evidence |

### Current level: **M3 — Evaluated System** (foundation core)

**Supporting evidence:**

- Phases 2–10, 12–13 covered by dedicated automated tests.
- Deterministic synthetic golden suite (26 cases) with baseline compare; CI `foundation-benchmark.yml`.
- Committed sample evidence (approve / reject / escalate) with `foundation-verify` valid.
- Explicit separation of technical evaluation, policy, escalation, and non-authorizing metrics.
- Public narrative aligned to M3.

**Missing for M4:**

- Broader retained workload evidence beyond three sample outcomes.
- Realistic (non-stub) sandbox verification as first-class experiment.
- Human escalation loop beyond local markdown package.

**Missing for M5:**

- Real production deployments, incidents, or measured fleet SLOs — **none present**. Do not claim.

---

## 1.6 Three Highest-Value Credibility Gaps (Part XVI)

| Priority | Credibility Gap | Status | Notes |
| --- | --- | --- | --- |
| **P0** | Public narrative overclaims unified production control plane | **CLOSED 2026-09-22** | README + `current-state.md` rewritten to M3 / foundation-centric honesty |
| **P0** | Empty `evidence/` directory | **CLOSED 2026-09-22** | Sample approve/reject/escalate + `manifest.json`; all three `foundation-verify` valid |
| **P1** | Parallel stacks without a single authority map | Open | Smallest upgrade: `docs/control-authority-map.md` |

### Gap work type

| Gap | Implementation | Test | Evaluation | Documentation | Status |
| --- | --- | --- | --- | --- | --- |
| P0 narrative | No | No | No | Yes | **Done** |
| P0 evidence package | `scripts/generate_sample_evidence.py` | CLI verify | Generated samples | `evidence/README.md` | **Done** |
| P1 authority map | No | No | No | Yes | Open |

**Deferred (still valuable):** cryptographic integrity for foundation audit; live LLM ablation vs scripted baseline; wiring APPROVED → REPAIR_SUCCESS predicates; human decision resume loop; MCP/EvalForge.

---

## 1.7 Strongest evidence (≤3)

1. **Policy fail-closed + non-default APPROVE** — `ci_failure_orchestrator/foundation/policy.py` + `tests/test_foundation_phase_8_policy.py` + BENCH-POLICY-* → **E2–E3**
2. **Bounded retry with progress/fingerprint stops** — `foundation/retry.py` + phase 7 tests + BENCH-RETRY-* → **E2–E3**
3. **Golden synthetic suite with baseline gate** — `benchmarks/foundation/` + `foundation/benchmark/runner.py` + `.github/workflows/foundation-benchmark.yml` → **E3**

---

## 1.8 Audit conclusion (gate for Steps 6+)

This repository is a **credible M3 deterministic AI-governance control-plane simulation for CI failure remediation**, with strong tests and synthetic evaluation on the foundation stack. It is **not** yet an M4/M5 production reliability product.

**P0 credibility gaps are closed.** Remaining top gap: **P1** control-authority map across parallel stacks.

**Next (optional, after user approval):** claim–evidence register; Staff/Governance/Research portfolio docs (Steps 9–12) grounded only in verified claims; close P1.

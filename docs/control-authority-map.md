# Control authority map

**Purpose:** Name a single authority for each control concern across parallel stacks.  
**Canonical product path:** `ci_failure_orchestrator/foundation/` via `ci-orchestrator foundation-*`.  
**As of:** 2026-09-22 · closes audit gap **P1**.

When stacks disagree in vocabulary or outcome, **foundation wins** for portfolio claims, evidence packages, and golden-suite interpretation. Other stacks are adjacent libraries unless you deliberately compose them.

---

## 1. Stack roles

| Stack | Package / entry | Role | Default character |
| --- | --- | --- | --- |
| **Foundation** | `foundation/` · `foundation-run`, `foundation-benchmark`, inspect/verify/resume | **Authoritative control plane** | Deterministic; scripted/heuristic proposals; temp sandbox; fail-closed policy |
| **Governed** | `governed/` · `run`, `benchmark`, `explain`, `replay` | Parallel simulation composition | Dry-run oriented; SQLite store; separate policy/state machine |
| **Trust gateway** | `trust_gateway.py`, `trust_policy.py` · `trust-run` | Tool-proposal policy demo | YAML/MockLLM scenarios; **not** foundation policy |
| **Diagnosis** | `classifier`, `ranker`, `graph`, `causal` · `analyze`, `analyze-run` | RCA over jobs/logs | Inputs for humans or other stacks; does not authorize repair |
| **Release predicates** | `release_gates.py` | Library booleans | `REPAIR_SUCCESS` / `RELEASE_READY` / `PRODUCTION_SUCCESS` — **not** foundation terminals |
| **Legacy repair / control** | `repair_state_machine.py`, `control_plane*.py`, `supervisor.py`, … | Adjacent runtimes | Do not override foundation outcomes |

Foundation does **not** import governed or trust. The CLI wires stacks side-by-side only.

---

## 2. Authority by concern

| Concern | Authoritative module | Decision / artifact | Adjacent (non-authoritative for portfolio claims) |
| --- | --- | --- | --- |
| Orchestration state machine | `foundation/state_machine.py` + `foundation/runner.py` | `RunStatus` transitions; illegal transitions raise | `governed/state_machine.py`; `trust_gateway` `GatewayState`; root `state_machine.py` / `repair_state_machine.py` |
| Failure classification (control plane) | `foundation/classifier.py` | Feeds plan / policy | Root `classifier.py` (diagnosis CLI); `governed/classifier.py` |
| Tool planning & path-safe tools | `foundation/planner.py`, `foundation/tools.py` | Bounded tool plan; `_safe_relpath` | `governed/tools.py` |
| Repair proposal | `foundation` heuristic / `ScriptedProposalFactory` | Proposal under retry budget | Governed `DeterministicAgentModel`; MockLLM in trust |
| Sandbox execution | `foundation/sandbox.py` | Temp-copy workspace; stub/schedule verify allowed | Governed dry-run; `patch_sandbox.py` / trust isolated workspace |
| Real-repo proposals + verification | `service/` (composes foundation; `repo_fix.py` is a re-export shim) | `fix-repo`: patch file or provider CLI → disposable git worktree of the target repo → foundation evaluation/retry/policy/escalation | — |
| **Primary workspace mutation** | **None (deliberate)** | Policy `APPROVE` does **not** apply to primary tree | Governed may model later `APPLYING` states in its own SM — not foundation product path |
| **Target repository write** | `service.apply.apply_fix` only | Explicit operator command `fix-repo-apply`; requires durable `APPROVED` (policy or human), verified patch hash; creates a new branch + commit via a temporary index (working tree, index and current branch untouched); audited as `TARGET_PATCH_APPLIED` / `TARGET_BRANCH_PUSHED` / `TARGET_PR_OPENED` | — |
| Technical evaluation | `foundation/evaluator.py` | PASS/FAIL; fail-closed without target verification | `governed/evaluation.py`; root `evaluator.py` |
| Retry budget | `foundation/retry.py` | Finite; fingerprint / no-progress / security stops | Trust gateway retry/budget states |
| **Policy gate** | **`foundation/policy.py`** | `APPROVE` \| `REJECT` \| `ESCALATE`; default ≠ `APPROVE`; errors → `ESCALATE` | `governed/policy.py`; `trust_policy.py`; root `policy.py` |
| Human escalation | `foundation/escalation.py` + `persistence.apply_reviewer_decision` | Local review package → `AWAITING_HUMAN`; explicit `foundation-decide` → `APPROVED`/`REJECTED`/`DEFER` (APPROVE ≠ primary apply) | Trust `HUMAN_ESCALATION`; governed `AWAITING_HUMAN` |
| Durable run state + audit | `foundation/persistence.py` (facade over `durable.py`, `recovery.py`, `human_decision.py`) | `state.json` + append-oriented `events.jsonl` | `audit.HashChainedAuditLog` (diagnosis/trust); `governed/store.py` SQLite |
| Cryptographic audit integrity | **Not foundation** | Append-oriented only | Hash-chain lives in `audit.py` for other stacks |
| Observability / SLI / SLO | `foundation/observability/*` | Rebuild from artifacts; **never authorizes** | Root telemetry / OTEL helpers |
| Synthetic evaluation | `foundation/benchmark/*` | 26 golden cases + baseline CI | Governed 8-case suite (`benchmark` CLI) |
| Sample evidence | `evidence/sample-runs/**` | Verify via `foundation-verify` | — |
| Diagnosis RCA | Diagnosis CLI modules | Analysis output only | Not a policy or apply authority |
| Promotion gates | `release_gates.py` | Library predicates only | Must not be read as foundation terminal status |

---

## 3. Success vocabulary (do not merge)

| Term | Owner | Meaning |
| --- | --- | --- |
| `APPROVED` / `REJECTED` / `AWAITING_HUMAN` | Foundation `RunStatus` | Policy / escalation terminals. **`APPROVED` ≠ primary apply.** |
| Governed `APPROVED` → `APPLYING` / … | Governed SM only | Simulation vocabulary; not foundation evidence |
| Trust `SUCCESS` / `DENIED` / … | Trust gateway | Separate demo lifecycle |
| `REPAIR_SUCCESS` | `release_gates.repair_success` | Verification predicate library |
| `RELEASE_READY` | `release_gates.ReleaseReadinessResult.ready` | Layered release predicate library |
| `PRODUCTION_SUCCESS` | `release_gates.ProductionSuccessResult.successful` | Layered production predicate library |

Portfolio and audit claims about the control plane must use **foundation** terminals unless the claim explicitly names another stack.

---

## 4. CLI authority routing

| CLI command | Stack | Authority for claims? |
| --- | --- | --- |
| `foundation-run`, `foundation-benchmark`, `foundation-inspect`, `foundation-events`, `foundation-resume`, `foundation-decide`, `foundation-verify`, `foundation-operations-report`, `foundation-slo-check` | Foundation | **Yes** — canonical |
| `fix-repo` | Foundation (real proposal source + worktree sandbox) | **Yes** — same foundation terminals; never writes the target repo |
| `fix-repo-apply` | Operator side effect after `APPROVED` | Only command that writes to a target repo (new branch; optional push/PR) |
| `run`, `explain`, `replay`, `benchmark` | Governed | Simulation only |
| `trust-run` | Trust | Demo / adjacent |
| `analyze`, `analyze-run`, `classify`, `rank` | Diagnosis | RCA only |

---

## 5. Conflict resolution rules

1. **One policy engine per claim.** Do not cite trust YAML or governed policy as proof of foundation fail-closed behavior (or vice versa).
2. **Metrics never authorize.** Foundation observability cannot flip `REJECT`/`ESCALATE` to `APPROVE`.
3. **Evaluation PASS ≠ policy APPROVE ≠ primary apply.** All three separations are foundation invariants. Writing a target repo is a separate, explicit `fix-repo-apply` step that refuses anything but `APPROVED`.
4. **Hash-chained audit ≠ foundation durable log.** Claiming tamper-evident proof requires the `audit.py` stack (or future foundation work) — not the append-only foundation store alone.
5. **Release/production predicates are optional composition.** Wiring them into foundation terminals is future work, not current product behavior.

---

## 6. Related docs

- [repository-audit.md](repository-audit.md) — maturity, evidence levels, gap status  
- [architecture/current-state.md](architecture/current-state.md) — what exists today  
- [architecture/agent-execution-foundation.md](architecture/agent-execution-foundation.md) — foundation design  
- [security/threat-model.md](security/threat-model.md) — residual risk  

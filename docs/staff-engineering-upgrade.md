---
title: "CI Failure Orchestrator — Staff Engineer Upgrade Plan"
tags: [platform-engineering, reliability, architecture, ai-governance, portfolio]
---

# CI Failure Orchestrator — Staff Engineer Upgrade Plan

**Repository:** [Kozphy/ci-failure-orchestrator](https://github.com/Kozphy/ci-failure-orchestrator)  
**Prepared:** 2026-10-04  
**Assessment baseline:** [fa293845dd1a723a9ff28db66a9eab5540d8c37c](https://github.com/Kozphy/ci-failure-orchestrator/commit/fa293845dd1a723a9ff28db66a9eab5540d8c37c)  
**Status:** Architecture and work log; roadmap items remain proposed until demonstrated.

This note continues the discussion “比較 Rust Go 重寫 GitHub.” It records the problem, options, decisions, implementation phases, and evidence needed to evolve the existing project. The complete previously discussed coding-agent prompt is preserved in section 13.

“Staff Engineer signal” means inspectable engineering judgment, system design, reliability, security, and operational ownership. A portfolio project alone does not establish an employer's level, organizational influence, or production impact.

## Contents

1. [Goal and success criteria](#1-goal-and-success-criteria)
2. [Current state and assessment template](#2-current-state-and-assessment-template)
3. [Target lifecycle and contracts](#3-target-lifecycle-and-contracts)
4. [Architecture and authority boundaries](#4-architecture-and-authority-boundaries)
5. [Phased roadmap](#5-phased-roadmap)
6. [Architecture decision record plan](#6-architecture-decision-record-plan)
7. [Reliability, SLIs, and SLOs](#7-reliability-slis-and-slos)
8. [Evidence harness](#8-evidence-harness)
9. [Threat model](#9-threat-model)
10. [Testing strategy](#10-testing-strategy)
11. [Staff-signal mapping](#11-staff-signal-mapping)
12. [Deferred work and work log](#12-deferred-work-and-work-log)
13. [Coding Agent Prompt](#13-coding-agent-prompt)

## 1. Goal and success criteria

Evolve the existing Python foundation into a controlled multi-repository CI reliability system that can diagnose failures, propose minimal repairs, verify them in isolation, enforce policy, bound retries, involve humans, and retain reproducible evidence.

Preserve useful code and behavior. Add infrastructure or another language only when a measured requirement and an ADR justify the operational cost.

The upgrade is complete only when evidence demonstrates:

- At least two repository fixtures can produce concurrent, isolated incidents; repeated deliveries do not duplicate side effects.
- Classification carries sanitized evidence, version information, and explicit uncertainty.
- Repair proposals are bound to a repository, base commit, patch hash, and verification plan.
- Technical evaluation, policy approval, human decisions, and repository writes remain separate authorities.
- Unsafe, unknown, stale, or inconclusive outcomes stop or escalate; retry attempts, elapsed time, and cost are bounded.
- A candidate runs through a defined isolation boundary; missing verification never becomes success.
- A failed or stale canary cannot promote; rollback and recovery are demonstrated within a declared scope.
- Every consequential transition and attempted side effect has durable, reconstructable evidence.
- Operational reports include denominators, observation windows, missing data, and measured limitations.
- ADRs and the case study connect a failure mode to a decision, implementation, test, and retained result.

A fixture demonstration establishes laboratory behavior. Production readiness additionally requires deployment-specific security review, recovery drills, credentials and tenancy controls, an operating owner, and actual workload measurements.

## 2. Current state and assessment template

### 2.1 Snapshot from the repository

This is a scoped source/document review at the baseline commit, not a fresh execution of the test suite or a production audit. Use the current code and commands to refresh it before implementation.

| Capability | Existing evidence | Assessment and next gap |
| --- | --- | --- |
| Canonical control plane | [foundation runner](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/foundation/runner.py), [state machine](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/foundation/state_machine.py), [authority map](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/docs/control-authority-map.md) | Explicit local lifecycle exists. Preserve foundation as the authority; adjacent stacks do not automatically compose into a product. |
| Classification and domain contracts | [models](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/foundation/models.py), [classifier](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/foundation/classifier.py) | Events include repository/commit metadata; confidence is heuristic. Repository fields alone do not prove durable multi-tenant isolation or event deduplication. |
| Proposal and real verification | [README](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/README.md), [service implementation](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/service), [patch sandbox](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/patch_sandbox.py) | Default foundation proposals are scripted/heuristic. Opt-in `fix-repo` verifies a supplied/provider patch in a disposable worktree after reproducing the failure. |
| Policy and retries | [policy](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/foundation/policy.py), [retry](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/foundation/retry.py) | `APPROVE / REJECT / ESCALATE`; conservative default and finite attempts exist. Retain fingerprints/no-progress stops; investigate crash-safe reservation and budgets across workers. |
| Isolation | [foundation sandbox](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/foundation/sandbox.py), real worktree path above | Temp-copy verification can use stubs. A worktree isolates files, not the host, network, processes, or secrets. Strong execution isolation needs a separate decision. |
| Human decisions and writes | [human decision](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/foundation/human_decision.py), [explicit apply](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/service/apply.py) | Local review packages and reviewer decisions exist. `fix-repo-apply` checks durable approval and patch hash, creates a new branch, and may open a draft PR. Reviewer delivery/authentication and stale approval handling need assessment. |
| Durable evidence | [persistence](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/foundation/persistence.py), [sample runs](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/evidence/sample-runs) | Local checkpoints and append-oriented events exist. Cryptographic audit in a separate stack does not make foundation evidence tamper-proof. |
| Evaluation harness | [benchmark docs](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/docs/evaluation/benchmark-harness.md), [foundation cases](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/benchmarks/foundation/cases) | The baseline tree contains 38 foundation cases. README reports 585 tests and 38/38 cases, with 26 baseline-held cases; those reported outcomes were not rerun for this note. |
| Operations | [SLI/SLO definitions](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/docs/operations/sli-slo.md), [observability](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/foundation/observability) | Reports rebuild local evidence; targets are provisional. Metrics never authorize repair. No measured fleet SLO is established. |
| Canary, release, fleet | [canary library](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/ci_failure_orchestrator/canary.py), [authority map](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/docs/control-authority-map.md) | Adjacent capabilities exist. A canary helper or workflow name does not prove a unified foundation ingestion-to-production lifecycle. |

The README also describes a real audit of the author's own repository and a real patch verification. These are useful bounded examples, not proof of independent customer adoption or production fleet impact.

Existing architecture/audit documents carry older date labels and counts. Resolve differences against the inspected revision, record the discrepancy, and update those documents in a later implementation change. The older [target architecture](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/docs/architecture/target-architecture.md) describes the governed stack; it must not silently redefine foundation authority.

### 2.2 Phase 0 assessment template

Refresh the existing `docs/architecture/current-state.md` rather than creating a competing source of truth. Complete this worksheet before runtime changes:

~~~markdown
### Assessment record
- Assessed revision:
- Date / assessor / scope:
- Commands executed and retained output:
- Sources reviewed:
- Explicitly unverified boundaries:

### Component and execution inventory
| Concern | Entrypoint / authoritative module | Current contract and store | Failure behavior | Test / artifact | Gap / smallest change |
| --- | --- | --- | --- | --- | --- |

Include ingestion, classification, proposals, sandbox, evaluation, retries,
policy, human decisions, apply/PR, persistence, observability, and deployment.

### Findings
- Current component diagram and one complete incident trace:
- Existing strengths and behavior to preserve:
- Conflicting authority or success terminology:
- Missing production capabilities:
- Security and recovery risks:
- Existing unnecessary complexity:
- Current baseline metrics with sample counts:
- Prioritized gaps, dependencies, and non-goals:

### Proposed next slice
- Failure mode:
- Options and trade-offs:
- Smallest change:
- Acceptance test and evidence path:
- Rollback:
- ADR to create or amend:
~~~

Use `Implemented / Tested / Measured / Production-proven` as separate columns when making capability claims. An existing test file is not evidence that it passed on this revision.

## 3. Target lifecycle and contracts

The discussion's target is:

~~~text
Multi-repo CI failures → classification → policy-based proposal
→ sandbox → evaluation → bounded retry or canary
→ human escalation when needed → audit evidence → SLO/reporting
~~~

This is a branching workflow. Escalation can happen before execution, after evaluation, at retry exhaustion, or after a canary regression. Audit and observability accompany every stage.

The current foundation puts its final policy gate after technical evaluation. Preserve that ordering unless an ADR changes it. Add a distinct pre-execution admission check for dangerous commands or workloads; a post-evaluation gate cannot contain code already executed.

### 3.1 Proposed orchestration boundaries

~~~mermaid
flowchart TD
    A["GitHub failure events"] --> B["Validate, normalize, deduplicate"]
    B --> C["Repository-scoped incident and durable state"]
    C --> D["Sanitized context and classification"]
    D --> E["Plan and hash-bound repair proposal"]
    E --> F{"Execution admission"}
    F -->|"blocked or uncertain"| H["Human review or rejection"]
    F -->|"permitted"| S["Isolated sandbox verification"]
    S --> V{"Technical evaluation"}
    V -->|"failed or inconclusive"| R{"Retry budget and progress"}
    R -->|"remaining"| E
    R -->|"exhausted or unsafe"| H
    V -->|"pass"| P{"Foundation policy gate"}
    P -->|"reject"| X["Rejected"]
    P -->|"escalate"| H
    P -->|"approve"| O["Approved candidate"]
    H -->|"explicit valid approval"| O
    O --> W["Explicit apply to new branch and draft PR"]
    W --> K{"Canary and fresh verification"}
    K -->|"regression or stale"| Q["Stop, revert candidate, escalate"]
    K -->|"pass plus required approval"| M["Controlled promotion"]
    C -.-> J["Durable audit for every transition and side effect"]
    H -.-> J
    X -.-> J
    Q -.-> J
    M -.-> J
    J --> Z["Non-authorizing metrics and SLO reports"]
~~~

In the target diagram, canary and promotion are planned integration. `APPROVED` remains the existing foundation terminal; it does not currently mean canary-passed, merged, or deployed.

### 3.2 Contract evolution

Extend/version existing dataclasses rather than replacing them wholesale.

| Contract | Fields to retain or add | Required behavior |
| --- | --- | --- |
| Normalized event | provider delivery ID; installation/repository/workflow IDs; CI run and attempt; head SHA; timestamp; source kind | Reject malformed/unsigned live input; separate webhook deduplication from logical incident identity; reconcile out-of-order deliveries. |
| Incident state | stable incident ID; repository scope; status/version; owner/lease; deadlines; retry budget/reservations; correlation ID | Atomic state updates; no cross-repository lookups; expired owners recover without repeating an external write. |
| Classification | category; evidence refs; confidence; calibration flag; classifier/rule version | Unknown and insufficient evidence remain explicit; labels cannot grant permissions. |
| Proposal | proposal ID/version; base SHA; exact patch hash; paths; rationale; permissions; risk; verification plan; rollback | Derive actual changed paths from the patch; approval binds the exact proposal and policy version. |
| Sandbox/evaluation | environment and image digest; executed commands; exit/timeout status; target reproduction; checks; artifacts; evaluator version | Distinguish failure, unavailable, inconclusive, and simulated checks; missing target verification cannot pass. |
| Policy/human decision | authoritative outcome; matching rules; policy version; reviewer identity; reason; scope; expiry; proposal hash | Preserve `APPROVE / REJECT / ESCALATE`. Future canary/approval conditions are explicit versioned requirements, not synonyms that bypass current gates. |
| Canary/promotion | candidate SHA; allowed scope; observations/window; baseline; criteria; decision; rollback ref | No promotion with missing/stale evidence, expired approval, or failed checks. |
| Audit event | event/incident/repository IDs; sequence; actor; before/after; input/output hashes; versions; result | Retain an append-oriented history; surface persistence failures before consequential side effects. |

Critical invariants: no automatic `AWAITING_HUMAN` exit, no mutation from metrics, no default approval, no bypass of a denial, no retry overspend after a restart, and no reusing approval for another patch/base/repository. Human approval cannot substitute for missing technical verification.

## 4. Architecture and authority boundaries

Keep one cohesive Python control plane initially. The GitHub adapter, state store, proposal provider, sandbox executor, evaluator, policy engine, reviewer channel, and metrics sink should be replaceable boundaries with explicit contracts.

| Plane | Responsibility | Authority limit |
| --- | --- | --- |
| Ingestion | Authenticate provider input; normalize and durably record | Cannot request privileged tools from event content. |
| Control/state | Legal transitions, replay, leases, deadlines, budgets | Must not overwrite policy or infer production success from a terminal name. |
| Proposal | Generate a candidate and evidence-backed rationale | Cannot execute arbitrary model-generated commands or grant access. |
| Execution | Apply and verify exact candidate in disposable isolation | No host credentials, production tokens, or primary-tree writes. |
| Evaluation | Assess target repair, regression, scope, security, uncertainty | Technical PASS is not permission to write, merge, or deploy. |
| Policy/review | Apply repository rules and explicit reviewer decisions | Approval binds exact artifact, versions, and scope. |
| Apply/promotion | Execute permitted side effects, reconcile retries, record receipts | New branch/draft PR first; never auto-merge because a sandbox is green. |
| Evidence | Reconstruct decisions and state changes | Append-oriented storage alone does not establish tamper resistance. |
| Observability | Explain latency, outcomes, costs, queue and human load | A report cannot authorize orchestration. |

Start with the current file store for a single-worker lab. Decide whether to retain it or introduce transactional persistence only after testing concurrency, crash recovery, and uniqueness requirements. Existing governed SQLite is an option to evaluate, not foundation's current authoritative store.

For languages: first document keeping Python. Consider Go for an independently justified concurrent service, or Rust for a measured component with a suitable safety/performance requirement. Compare Python fixes, profiling, migration risk, deployment, interface maintenance, and team cost before selecting either. A complete rewrite is deferred.

## 5. Phased roadmap

The numbers below preserve the original prompt's phases. They describe assessment and integration work, not a claim that similarly numbered foundation phases are absent or complete. Reuse existing implementations and document the delta.

| Phase | Smallest useful slice | Exit evidence |
| --- | --- | --- |
| 0 — Assessment | Refresh current-state and claim/evidence inventory at a pinned revision | Component diagram, baseline commands/results, ranked gaps, authority map. |
| 1 — Domain | Extend existing incident/state contracts; version migration and invariants | Legal/illegal transitions, stale updates, crash/recovery tests. |
| 2 — Ingestion | Repository-scoped signed events and durable deduplication for two lab repos | Duplicate, reordered, malformed, concurrent, restart/replay traces; no duplicate side effects. |
| 3 — Classification | Extend current rules and labeled failure corpus; keep abstention | Per-class precision/recall/F1 and confusion matrix with sample counts; unknown cases. |
| 4 — Proposals/policy | Bind proposals and actual patch scope; preserve final foundation gate | Allowed/rejected/escalated cases; edited-patch and wrong-repository approvals blocked. |
| 5 — Isolation | Separate execution admission from final policy; enforce sandbox limits | Timeout, process/egress/path/secret containment and cleanup evidence. |
| 6 — Evaluation | Reproduce baseline failure; verify candidate and regressions | PASS/FAIL/inconclusive/unavailable outcomes; unchanged or regressive patch fails. |
| 7 — Retry | Keep fingerprint/progress stops; reserve attempts, time and cost durably | Exhaustion, repeated proposals, worker crash and concurrent budget contention traces. |
| 8 — Canary | Compose existing helper into one lab candidate workflow | Declared candidate scope/window, pass, regression, stale base, rollback, no false promotion. |
| 9 — Human | Extend local packages with authenticated decisions and timeout/revocation | Identity, scope/hash/expiry checks; approve/reject/defer/request-changes; no auto-approval. |
| 10 — Audit | Cover transition and side-effect crash boundaries | Reconstruct one lifecycle; corruption/missing-write detection; reconciliation receipts. |
| 11 — Reliability | Define eligibility, SLIs, provisional targets and error budgets | Windowed report with denominators, missing data and sample thresholds. |
| 12 — Reporting | Extend existing metrics/export before adding a UI | Per-repo/class outcomes, latency percentiles, retries, policy blocks, unknown and human backlog. |
| 13 — Failure injection | Add representative dependency and control-plane faults | Expected/actual/recovery/signal/evidence matrix; no safety bypass. |
| 14 — ADRs | Review existing ADRs; add only meaningful new decisions | Accepted decisions linked to implementation, tests, limitations and revisit triggers. |
| 15 — Threat model | Scope foundation, real executor and provider boundaries | Threat/control/test/residual-risk register; stack-specific claims. |
| 16 — Observability | Stable incident/proposal/attempt correlation across boundaries | End-to-end trace reconstruction; redaction and metrics-outage behavior. |
| 17 — Tests | Close contract, state-machine, isolation and side-effect gaps | Relevant suite passes at revision; current baseline checked without auto-updating it. |
| 18 — Evidence | Compose existing benchmark/sample/demo commands into one repeatable run | Manifest, hashed artifacts, failures surfaced, source-kind labels. |
| 19 — Case study | Write problem, constraints, decisions, failures and measured results | Reviewer can follow ADR → code → test → fault → artifact → metric. |
| 20 — README | Update public claims after evidence exists | Every capability has evidence and scope; deferred/production gaps remain visible. |

ADRs, threat modeling, tests, and evidence are continuous across phases; do not postpone them to their numbered row.

Execution batches:

- **Batch A:** Phases 0–2 only; establish baseline, contracts, and multi-repository isolation.
- **Batch B:** Phases 3–7 with focused ADR/security/testing work; keep unsafe execution disabled until the isolation boundary is demonstrated.
- **Batch C:** Phases 8–10; integrate lab canary, reviewer workflow, and durable side effects.
- **Batch D:** Complete reporting, fault matrix, evidence wrapper, case study, and README; add a real pilot only under an explicit operating scope.

For every slice: inspect → describe gap → decide → implement → test → inject failure → retain evidence → update note/ADR. Stop the slice when its exit criteria are met.

## 6. Architecture decision record plan

An ADR records context, alternatives, the decision, consequences, risks, and revisit conditions. It demonstrates why the architecture changed.

The repository already has ADRs `0001–0007`. Preserve their filenames and meanings. In particular, [ADR-0003](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/docs/adr/0003-durable-orchestration-state.md) concerns governed SQLite; it is not evidence that foundation has the same store. The original prompt's `ADR-001…011` list is an illustrative topic list, not permission to overwrite existing records.

| Topic | Existing record / proposed follow-up |
| --- | --- |
| Planning vs execution / proposal vs remediation | Review `0001`; extend rationale for admission and exact proposal identity. |
| Tool permissions and isolation | Review `0002`; propose `0009` for the real executor's isolation boundary. |
| Durable foundation workflow / idempotency | Review `0003` in its stack; propose `0008` for incident identity, uniqueness, leases, crash-safe side effects and recovery. |
| Evaluation gate | Review `0004`; document target reproduction and inconclusive behavior. |
| Durable retry budget | Review `0005`; amend only for changed semantics. |
| Policy / approval / canary conditions | Review `0006`; propose `0010` for reviewer identity/expiry/revocation and `0011` for canary promotion/rollback. |
| MCP-ready boundary | Preserve `0007`; live MCP remains deferred. |
| Audit integrity and retention | Propose `0012`; distinguish integrity, confidentiality, durability and access control. |
| Observability / SLO semantics | Propose `0013`; eligibility, data completeness, error budgets, non-authorizing sinks. |
| Classification and uncertainty | Propose `0014` only if the classifier design changes. |
| Python / Go / Rust | Propose `0015` based on profiling and service requirements; keeping Python is valid. |

All proposed numbers must be checked against the latest ADR index before creation. None of these new ADRs is created or accepted by this planning note.

~~~markdown
# ADR-NNNN: Decision title

## Status
Proposed / Accepted / Superseded (with replacement link)

## Context
Failure mode, constraints, measured baseline, affected authority.

## Decision
Smallest chosen design; trust boundary and rollback.

## Alternatives considered
Options, evidence, operational cost, rejected trade-offs.

## Consequences
Benefits, costs, limitations, compatibility and migration.

## Risks
Failure modes, residual security risk, mitigation owner.

## Verification
Implementation, tests, failure-injection artifacts and result.

## Revisit conditions
Measurable trigger, owner, date.
~~~

## 7. Reliability, SLIs, and SLOs

Reuse [the foundation catalog](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/docs/operations/sli-slo.md). Its current targets are `EXAMPLE_TARGET / provisional`, not measured production commitments. The original prompt's numerical examples are proposals only.

| SLI / guardrail | Measurement | Initial proposed target / interpretation |
| --- | --- | --- |
| Detection latency | Provider failure time to durable accepted incident, with clock skew and delivery delay reported | 95% ≤60 seconds over a declared 30-day live pilot window; requires a reconciled provider inventory. Offline timings do not qualify. |
| Proposal latency | Accepted incident to first valid proposal; timeout/noncompletion counts as a miss | 95% ≤5 minutes for the explicitly allowlisted repair classes; report excluded classes separately. |
| Incorrect-repair rate | Confirmed incorrect candidates / reviewed completed candidates; unresolved outcomes separately | <2% is an experimental target requiring labels, enough samples and uncertainty bounds. Do not treat policy coverage as accuracy. |
| Audit/persistence completeness | Runs with all mandatory records / all accepted runs assessed, including failed runs | Proposed ≥99%; consequential operations require their audit preconditions regardless of aggregate target. |
| Retry compliance | Attempts/time/cost within budget / eligible attempted incidents | Hard invariant: no overspend. Any observed violation blocks widening automation. |
| Approval integrity | Unauthorized or wrong-patch writes/promotions | Hard invariant: zero. No error-budget allowance for bypassing a required control. |
| Service availability | Valid requests durably accepted within deadline / valid requests observed independently | Establish baseline before choosing a percentage; provider and storage outages remain visible. |
| Diagnosis/recovery time | Distributions over declared populations; unresolved incident age separately | Report p50/p95, sample counts and censored outcomes. No invented improvement over a missing baseline. |

Record window start/end, repository scope, denominator, missing records, source kind, target version, and `PROPOSED / EXPERIMENTAL / MEASURED` status. Zero denominators yield `INSUFFICIENT_DATA`. Do not call retained local samples a 30-day production SLO.

For a ratio target `t` and eligible count `N`:

~~~text
allowed_bad = (1 - t) * N
observed_bad = N - good
remaining_budget = allowed_bad - observed_bad
~~~

When an actual pilot exhausts its operational budget: stop widening rollout, keep read-only diagnosis/evidence collection available, investigate and retain the incident, and resume only after the documented recovery criteria pass. Safety controls are always mandatory.

Keep reconstruction evidence in the durable control path. A failed metrics export may degrade reporting without changing authorization; a failed required audit write must stop the consequential operation.

## 8. Evidence harness

Build on the existing foundation benchmark, four sample runs, real-patch path, and offline doctor demo. Do not replace them with a second harness merely to create a new command.

Existing commands documented in the inspected README (run after the repository's normal installation):

~~~bash
ci-orchestrator foundation-benchmark --required-only --compare-baseline
python scripts/generate_sample_evidence.py
ci-orchestrator foundation-verify sample-approve --artifacts evidence/sample-runs/01-approve
ci-orchestrator foundation-verify sample-reject --artifacts evidence/sample-runs/02-reject
ci-orchestrator foundation-verify sample-escalate --artifacts evidence/sample-runs/03-escalate
ci-orchestrator foundation-verify sample-human-approve --artifacts evidence/sample-runs/04-human-approve
actions-doctor demo --all
~~~

Sample regeneration writes local artifacts; it is not a deployment. These commands were not executed as part of creating this note.

A future `make evidence` or `python -m tools.evidence` wrapper is **proposed**, not available because this note mentions it. It should capture source revision, environment/dependency versions, seed, fixture hashes, command exits, actual verification, failures, artifact hashes, and source kind. Required scenario failures must return a failing exit status; golden expectations must never update automatically.

~~~text
artifacts/evidence/<run-id>/       # proposed consolidated output
├── manifest.json
├── summary.json
├── metrics.json
├── incident-trace.jsonl
├── policy-decisions.jsonl
├── retry-results.json
├── canary-results.json
├── threat-control-results.json
└── report.md
~~~

Use the repository's evidence levels: E0 concept, E1 code, E2 tests, E3 repeatable evaluation, E4 retained runtime/controlled simulation, E5 real production. Mark simulation explicitly; it does not become E5 by running in GitHub Actions.

Minimum retained scenario set: allow, deny, escalate, human approve without automatic apply, retry exhaustion, duplicate/reordered event, two repositories concurrently, forbidden patch, unavailable verification, sandbox timeout/crash, provider malformed output/timeout, policy error, database/audit failure, stale/revoked approval, restart during side effect, failed canary and successful rollback.

Compare the controlled design with an ungated/unlimited-retry **simulation baseline**; never disable safety on a live repository to run an ablation. Report both unsafe approvals and useful repairs, abstention, cost and latency so a system that rejects everything cannot look deceptively effective.

| Capability | Test/scenario | Artifact and revision | Result | Source kind / evidence level |
| --- | --- | --- | --- | --- |
| Policy deny blocks write | Forbidden patch | To be populated after execution | NOT_RUN | Synthetic / planned |
| Retry cap survives crash | Concurrent reservation/restart | To be populated after execution | NOT_RUN | Reproduced / planned |
| Cross-repository isolation | Two simultaneous incidents | To be populated after execution | NOT_RUN | Synthetic / planned |
| Failed canary blocks promotion | Injected regression | To be populated after execution | NOT_RUN | Controlled lab / planned |

## 9. Threat model

Extend the existing [threat model](https://github.com/Kozphy/ci-failure-orchestrator/blob/fa293845dd1a723a9ff28db66a9eab5540d8c37c/docs/security/threat-model.md) with explicit foundation, `fix-repo` executor, provider, reviewer, and GitHub boundaries. Its current governed/dry-run controls do not automatically secure the real command executor.

Assets: source/CI configuration, runner host, credentials, installation/repository identity, patch and approval integrity, retry/cost budgets, and evidence. Treat repository files, tests, logs, issues and generated patches as untrusted.

All mitigations below are requirements to verify, not claims that they are implemented.

| Threat and attack path | Impacted asset / impact | Mitigation and acceptance evidence | Residual risk |
| --- | --- | --- | --- |
| Malicious PR or test script executes in verification | Host, secrets; arbitrary code execution | Disposable least-privilege executor, no credentials, enforce process/resource/egress limits; containment scenario | Worktrees alone do not contain execution; kernel/runtime vulnerabilities remain. |
| Prompt injection in logs/repository asks provider to run privileged tools | Permissions/source; unauthorized action | Bounded sanitized context, structured proposals, independent policy, restricted provider CLI tools; malicious-context fixture | Redaction is not a complete prompt-injection defense. |
| Shell/argument injection from event or generated command | Host; arbitrary command execution | Operator-defined execution policy, typed argument boundaries, no model-selected shell text; injection tests | Legitimate allowed tools can execute repository code. |
| Secret leakage through provider prompt, logs or evidence | Tokens/private source; exfiltration | Redaction before external transmission, environment allowlist, short-lived scoped credentials, retention/access controls; leak fixture | Unknown formats and already-public output may evade detection. |
| Dependency poisoning | Executor/network; compromised build | Pinned/provenance-checked inputs, controlled dependency retrieval and egress; poisoned-package scenario | Upstream supply-chain compromise is not eliminated. |
| Traversal/symlink/extra-file patch escapes proposal scope | Source/host; unauthorized writes | Canonicalize paths, inspect actual diff, block symlink escapes, hash-bound scope; adversarial patch tests | Filesystem race and parser discrepancies need platform testing. |
| Compromised GitHub token or forged webhook | Repository identity; unauthorized ingestion/write | Verify webhook signatures/replay limits, least privilege per installation, token rotation and separated write worker; invalid signature fixture | Credential theft remains incident-response work. |
| Cross-repository contamination or confused deputy | Tenancy; one repo gains another's permissions | Namespace events/state/artifacts and resolve credentials from trusted identity; same IDs across two repos fixture | Misconfigured external permissions remain possible. |
| Approval replay, stale base, malicious generated patch | Patch integrity; unsafe promotion | Bind base SHA, patch/policy versions, reviewer identity, expiry and revocation; recheck before write/promotion | Human review can still miss a semantic regression. |
| Audit tampering or crash between side effect and audit | Evidence; false history/duplicate action | Durable intent/receipt/reconciliation, restricted storage, integrity verification with protected anchors; corruption/restart tests | Hashes without protected anchors cannot prove non-tampering. |
| Privilege escalation/sandbox escape | Runner/control-plane host | Separate executor identity/host boundary; no shared secrets; security review and containment tests | Container isolation alone is not proof against hostile code. |
| Retry storm, provider timeout or oversized event | Availability/cost; exhaustion | Durable quotas, bounded input, deadlines, cancellation, backoff/jitter and per-repo fairness; exhaustion scenario | Provider outage and capacity limits remain. |

For each open risk record owner, severity, control status, test reference, residual exposure, and the condition that blocks a real pilot.

## 10. Testing strategy

Use the existing test/benchmark structure. Add tests for meaningful gaps rather than mirroring implementation details.

| Layer | What it must prove |
| --- | --- |
| Unit | Classification evidence/abstention, path parsing, policy precedence, budget arithmetic, redaction, SLI eligibility and zero-denominator semantics. |
| Contract | Versioned event/proposal/sandbox/reviewer/store schemas; malformed or unavailable results fail closed. |
| State machine / property | Illegal transitions rejected; automation cannot leave AWAITING_HUMAN; no approval/write without evidence; crash/replay cannot overspend. |
| Integration | Real disposable git worktree; failing baseline then exact patch; regression suite; durable reconstruction; target working tree/index/branch unchanged. |
| Security/policy | Traversal/symlink/injection/leak fixtures; denial blocks apply; changed patch/wrong repository/expired approval blocked; no credentials in executor. |
| Concurrency/recovery | Duplicate deliveries, same incident claimed by two workers, independent repo quotas, storage outage, crash before/after write, side-effect reconciliation. |
| Fault injection | GitHub unavailable, provider timeout/malformed response, sandbox crash/timeout, evaluator disagreement, policy error, audit failure, reviewer timeout, canary regression. |
| End-to-end lab | Two repositories: ingest → candidate → verify → policy/review → draft PR/canary → rollback or controlled promotion → evidence/report. Stubbed stages explicitly labeled. |

For every fault record expected behavior, actual behavior, recovery, observability signal and audit references. CI should run deterministic tests and baseline comparison; live tests stay opt-in with explicit scope, credentials and cleanup. Unsupported platforms or unavailable live services must appear as unverified, not pass.

Useful existing checks for the canonical foundation:

~~~bash
pytest tests/test_foundation_phases_2_6.py tests/test_foundation_phase_7_retry.py tests/test_foundation_phase_8_policy.py tests/test_foundation_phase_9_escalation.py tests/test_foundation_phase_10_persistence.py tests/test_foundation_phase_12_benchmark.py tests/test_foundation_phase_13_observability.py -q
ci-orchestrator foundation-benchmark --required-only --compare-baseline
~~~

Add the existing human-decision and real-repo tests when changing those boundaries. Run the full repository CI checks for runtime changes. This documentation-only publication validates structure, repository references and remote content; it does not claim a fresh runtime test pass.

## 11. Staff-signal mapping

| Work | Capability demonstrated | Evidence a reviewer needs |
| --- | --- | --- |
| One explicit authority model across parallel stacks | System design and scope judgment | Decision, boundary contract, conflicting-case test and trace. |
| Multi-repository identity and isolation | Platform engineering | Concurrent workloads, dedup/replay results, per-repo quota and permission tests. |
| Crash-safe state and side effects | Reliability and operational ownership | Recovery drill, no duplicated PR/write, incident reconstruction. |
| Admission, verification and policy separation | Security and AI governance | Malicious-input fixture, containment, deny/stale approval tests. |
| Budgets and progress-aware stops | Cost/reliability judgment | Bounded traces, cost/time distributions, behavior under provider outage. |
| Canary, rollback and reviewer lifecycle | Change management | Declared blast radius, regression stop, revocation/timeout, rollback evidence. |
| Honest SLIs and experiments | Measurement and observability | Numerators/denominators, uncertainty, baseline comparison and missing data. |
| ADRs with rejection/revisit criteria | Technical decision quality | Alternatives, operational cost, profiling, accepted decision linked to results. |
| Runbooks and adoption feedback | Cross-team communication | Operator walkthrough, external review, documented feedback and improved outcomes. |
| Case study and claim register | Credible portfolio presentation | ADR → code → tests → failure → artifact → metric, with remaining gaps. |

Production outcomes, organizational influence, adoption and collaboration require external evidence. Do not invent them from the presence of code or a polished architecture note.

## 12. Deferred work and work log

| Deferred item | Reason now | Revisit trigger |
| --- | --- | --- |
| Whole-repository Go/Rust rewrite | Existing Python boundaries can be assessed and improved first | Profiled bottleneck or independently justified component; migration ADR. |
| Kubernetes, Kafka, service mesh, microservice split | No measured need for their operational cost | Workload/capacity/availability requirement cannot be met by a simpler design. |
| Distributed consensus / elaborate event sourcing | Preserve a minimal transactional incident/event model | Recovery/scale requirements demonstrated beyond that model. |
| Vector database or graph-authorized repairs | Adds retrieval complexity; diagnosis cannot grant permissions | Measured diagnosis improvement; policy remains independent. |
| Multi-provider tournament as default path | Increase reproducibility and control before widening provider behavior | Ablation demonstrates value under bounded cost and risk. |
| Live MCP / EvalForge integration | Existing readiness docs do not establish live adapters | A concrete consumer and contract/integration evidence. |
| Production auto-merge/deploy | Canary and production operating scope remain unproven | Demonstrated isolation, approval/revocation, rollback and deployment-specific acceptance. |
| Large dashboard UI | Existing exports can answer operational questions first | Operators need interactions the reports cannot provide. |

Must resolve before a hostile-code production pilot: execution containment, tenant/auth boundaries, durable side-effect recovery, approval integrity, retention/security ownership, and deployment-specific recovery evidence.

Useful next: broaden real/reproduced failures, classifier labels, live-provider comparison, operator feedback, reviewer channel and measured pilot outcomes.

~~~markdown
### Work-log entry
- Date / phase / owner:
- Failure mode and current evidence:
- Options considered:
- Decision / ADR:
- Implementation revision and paths:
- Commands / tests / injected faults:
- Expected vs actual behavior:
- Retained artifacts and hashes:
- Metrics (population, window, sample count):
- Limitations / residual risks:
- Rollback or recovery:
- Next slice / explicit deferred work:
~~~

Initial entry, 2026-10-04: planning note prepared after a scoped baseline source review; original prompt recovered from the conversation, including its missing ending. No runtime upgrade, new ADR, test rerun, pilot deployment, or achieved SLO is implied by this entry.

## 13. Coding Agent Prompt

### 13.1 Repository-specific use instructions

The prompt below is the complete earlier prompt, with Markdown formatting normalized. It is archived as reusable source text, not a statement of current implementation.

When using it on this repository, apply these clarifications:

1. Inspect the current revision and existing guidance first; begin with Phases 0–2 only. Continue useful existing code rather than rebuilding completed foundation phases.
2. Refresh existing architecture/security/operations documents. Preserve the current ADRs and check the next unused number before adding one.
3. Keep foundation authority and `APPROVE / REJECT / ESCALATE` outcomes. The prompt's alternate policy vocabulary and lifecycle are illustrative design topics.
4. Preserve technical PASS ≠ policy approval ≠ write/merge/deploy. Use the explicit approved apply/new-branch/draft-PR path; do not turn a successful sandbox into permission.
5. Implement a pre-execution admission/isolation boundary as well as final policy. Treat real repository tests/provider tools as untrusted execution.
6. Treat retry failure, low confidence, missing evidence, stale approval and canary failure as stop/review paths. Escalation is conditional, not a mandatory stage after successful rollout.
7. Reuse benchmark/sample/demo tools; proposed commands and artifacts do not exist until implemented and demonstrated.
8. The prompt is for later coding work. This note's scope is documentation; proposed SLOs and Staff scores must never be presented as measured production capability.

### 13.2 Complete previously discussed prompt

Copy the text inside this block into the coding agent, together with the repository-specific use instructions above.

~~~~markdown
# Staff-Level Upgrade: Multi-Repo CI Failure Orchestrator

You are acting as a **Staff Software Engineer / Platform Reliability Engineer / AI Systems Architect**.

Your task is to inspect my existing `ci-failure-orchestrator` repository and evolve it into a credible **production-oriented, multi-repository CI reliability control plane**.

Do NOT rewrite the repository from scratch.

Do NOT add complexity just to look sophisticated.

Do NOT migrate languages unless there is a clear engineering reason supported by an ADR.

Your goal is to maximize **Staff Engineer signal** through architecture quality, reliability, failure handling, observability, policy, evidence, and engineering judgment.

---

# Target Architecture

The final system should support this end-to-end lifecycle:

```text
Multi-repo CI failures
        ↓
Failure classification
        ↓
Policy-based repair proposal
        ↓
Sandbox execution
        ↓
Evaluation
        ↓
Retry budget
        ↓
Canary rollout
        ↓
Human escalation
        ↓
Audit evidence
        ↓
SLO / reliability dashboard
```

The important goal is NOT merely to make this diagram exist.

Every stage must have:

- explicit contracts
- state transitions
- failure modes
- observability
- tests
- evidence
- documented architectural decisions

---

# Phase 0 — Inspect Before Changing Anything

First inspect the entire repository.

Identify:

1. Current architecture
2. Entry points
3. CI integrations
4. Existing retry logic
5. Current failure classification
6. Existing persistence
7. Existing evaluation logic
8. Existing approval / policy mechanisms
9. Logging and audit evidence
10. Tests
11. Deployment architecture
12. Security boundaries
13. Existing ADRs
14. Known technical debt
15. Existing functionality that should NOT be rewritten

Create:

```text
docs/architecture/current-state.md
```

Include:

- current component diagram
- current request/job flow
- existing strengths
- missing production capabilities
- architectural risks
- unnecessary complexity already present
- Staff-level gaps

Do not modify production code until this assessment is complete.

---

# Phase 1 — Define the Domain Model

Create an explicit lifecycle for a CI incident.

Example:

```text
DETECTED
   ↓
CLASSIFIED
   ↓
PROPOSAL_CREATED
   ↓
POLICY_CHECKED
   ↓
SANDBOX_RUNNING
   ↓
EVALUATED
   ↓
RETRY_ALLOWED
   ↓
CANARY
   ↓
VERIFIED
   ↓
RESOLVED
```

Alternative exits:

```text
REJECTED
ESCALATED
RETRY_EXHAUSTED
POLICY_BLOCKED
SANDBOX_FAILED
CANARY_FAILED
MANUAL_INTERVENTION_REQUIRED
```

Define a durable incident/job model containing at least:

```text
incident_id
repository_id
workflow_id
run_id
commit_sha

failure_class
confidence

proposal_id
proposal_version

policy_decision

retry_count
retry_budget

sandbox_result
evaluation_result

canary_status

human_decision

created_at
updated_at
resolved_at

correlation_id
trace_id
```

Document the state machine and invariants.

Important invariants may include:

- a repair cannot deploy before policy approval
- retry count cannot exceed retry budget
- the same workflow event must not generate duplicate repairs
- an incident must maintain a complete audit trail
- canary failure must prevent wider rollout
- low-confidence repairs require escalation

---

# Phase 2 — Multi-Repository Failure Ingestion

Upgrade the system so that failures can be handled across multiple repositories.

Design a repository abstraction rather than hard-coding one repository.

Support concepts such as:

```text
organization
repository
workflow
branch
commit
CI run
failure event
```

Create an ingestion boundary such as:

```text
GitHub webhook
      ↓
Event normalization
      ↓
Deduplication
      ↓
Incident creation
```

Requirements:

- idempotent event processing
- duplicate webhook protection
- correlation IDs
- repository isolation
- configurable repository policies
- replayable events where practical

Test:

- duplicate delivery
- out-of-order events
- missing metadata
- malformed events
- simultaneous repository failures

---

# Phase 3 — Failure Classification

Create an explicit failure taxonomy.

Example categories:

```text
dependency_failure
test_failure
lint_failure
build_failure
configuration_failure
environment_failure
network_failure
timeout
flaky_test
permission_failure
secret_configuration_failure
external_service_failure
unknown
```

Classification output should contain:

```json
{
  "failure_class": "...",
  "confidence": 0.0,
  "evidence": [],
  "classifier_version": "...",
  "requires_human_review": false
}
```

Separate:

```text
observation
classification
decision
action
```

Never allow an LLM classification alone to automatically trigger a high-risk remediation.

Add deterministic rules wherever practical.

Track classification quality using:

```text
precision
recall
F1
false-positive rate
unknown rate
```

---

# Phase 4 — Policy-Based Repair Proposal

Repair generation must produce a **proposal**, not immediately modify production.

Use a contract similar to:

```text
RepairProposal

proposal_id
incident_id
files_changed
patch
rationale
expected_effect
risk_level
confidence
required_permissions
estimated_blast_radius
rollback_strategy
```

Add a policy engine.

Example policies:

```text
ALLOW
ALLOW_WITH_CANARY
REQUIRE_HUMAN_APPROVAL
DENY
```

Possible policy inputs:

```text
repository criticality
branch
files touched
failure class
proposal confidence
security-sensitive files
infrastructure files
retry history
blast radius
historical success rate
```

Examples:

```text
README change
→ ALLOW

test-only change
→ ALLOW_WITH_CANARY

production infrastructure
→ REQUIRE_HUMAN_APPROVAL

authentication / secrets
→ REQUIRE_HUMAN_APPROVAL

security controls
→ REQUIRE_HUMAN_APPROVAL

unknown high-risk patch
→ DENY
```

Policies must be auditable.

---

# Phase 5 — Sandbox Execution

No untrusted repair should execute directly in production.

Create an isolated execution boundary.

Conceptual flow:

```text
Repair Proposal
       ↓
Temporary Workspace
       ↓
Apply Patch
       ↓
Install Dependencies
       ↓
Build
       ↓
Tests
       ↓
Static Checks
       ↓
Security Checks
       ↓
Result
```

The sandbox must implement:

- timeout
- resource limits where available
- command allow-list or explicit execution policy
- network policy where practical
- workspace cleanup
- immutable input metadata
- structured output

Return something similar to:

```json
{
  "sandbox_id": "...",
  "proposal_id": "...",
  "exit_status": "...",
  "tests_passed": 0,
  "tests_failed": 0,
  "duration_ms": 0,
  "artifacts": [],
  "logs": [],
  "security_findings": []
}
```

---

# Phase 6 — Evaluation Layer

Do not use:

```text
tests passed = repair successful
```

Create a richer evaluation layer.

Evaluate:

```text
target failure fixed?
regressions introduced?
tests passed?
new warnings?
security regression?
performance regression?
policy compliance?
unexpected files modified?
```

Produce:

```text
EvaluationResult

correctness_score
regression_score
security_score
confidence
decision
evidence
```

Possible decisions:

```text
PASS
FAIL
INCONCLUSIVE
REQUIRES_HUMAN
```

Maintain an evaluation version so historical outcomes remain reproducible.

---

# Phase 7 — Retry Budget

Implement bounded retries.

Never create:

```text
while failure:
    ask_agent_again()
```

Create a retry budget based on factors such as:

```text
failure class
risk level
historical success rate
cost
token usage
time
previous attempts
proposal similarity
```

Example:

```text
Attempt 1
↓
Evaluation failed

Attempt 2
↓
Different repair strategy

Attempt 3
↓
Budget exhausted

Human escalation
```

Prevent semantically identical repair attempts.

Record:

```text
attempt
strategy
cost
duration
evaluation_result
reason_for_retry
```

---

# Phase 8 — Canary Rollout

A successful sandbox result must not automatically mean full deployment.

Introduce a canary stage.

Example:

```text
sandbox success
      ↓
temporary branch
      ↓
PR / isolated workflow
      ↓
targeted tests
      ↓
canary observation window
      ↓
promote OR rollback
```

Define:

```text
promotion criteria
rollback criteria
observation window
blast radius
```

Canary failure must generate evidence and prevent promotion.

---

# Phase 9 — Human Escalation

Humans must receive useful context rather than raw logs.

Create an escalation packet containing:

```text
incident summary
failure classification
root-cause evidence
repair proposal
files modified
evaluation result
retry history
risk level
policy decision
recommended human action
```

Possible actions:

```text
APPROVE
REJECT
REQUEST_NEW_PROPOSAL
MARK_FALSE_POSITIVE
TAKE_MANUAL_OWNERSHIP
```

Record who made the decision and why.

---

# Phase 10 — Audit Evidence

Treat audit evidence as a first-class feature.

Every important system event should produce structured evidence.

Example:

```json
{
  "event_id": "...",
  "timestamp": "...",
  "incident_id": "...",
  "actor": "...",
  "action": "...",
  "input_hash": "...",
  "output_hash": "...",
  "policy_version": "...",
  "result": "..."
}
```

Prefer append-only semantics.

Evidence should answer:

```text
What happened?
When?
Why?
Which system/user made the decision?
Which evidence was used?
Which model/rule/policy version was involved?
What changed?
Was human approval involved?
What happened afterward?
```

Add redaction for:

```text
secrets
tokens
credentials
personal information
sensitive environment variables
```

---

# Phase 11 — Reliability Model

Define explicit SLI/SLO targets.

Possible SLIs:

```text
failure detection latency
classification latency
repair success rate
false repair rate
mean time to diagnosis
mean time to recovery
retry exhaustion rate
human escalation rate
canary rollback rate
pipeline availability
```

Example SLOs:

```text
95% of CI failures detected within 60 seconds.

95% of classified incidents receive a repair proposal within 5 minutes.

Automated repair false-positive rate < 2%.

99% of audit events are persisted successfully.

No repair exceeding configured risk level is deployed without required approval.
```

Do not invent impressive numbers without measurement.

If production data is unavailable, label them:

```text
proposed SLO
experimental target
measured baseline
```

---

# Phase 12 — Dashboard

Create a reliability dashboard or an exportable metrics layer.

At minimum show:

```text
Incidents by repository
Incidents by failure class
Repair success rate
Retry distribution
Human escalation rate
Mean time to diagnosis
Mean time to recovery
Canary rollback rate
Policy blocks
Unknown classification rate
```

Support time windows.

Prefer metrics that answer operational questions rather than vanity metrics.

---

# Phase 13 — Failure Injection / Chaos Scenarios

Create reproducible failure scenarios.

Test at least:

```text
GitHub API unavailable
duplicate webhook
database unavailable
LLM timeout
LLM malformed response
sandbox timeout
sandbox crash
evaluation disagreement
policy engine failure
retry exhaustion
canary regression
audit persistence failure
human approval timeout
```

For every scenario document:

```text
expected behavior
actual behavior
recovery behavior
observability signal
audit evidence
```

---

# Phase 14 — Architecture Decision Records

Create:

```text
docs/adr/
```

Write ADRs for meaningful architectural decisions.

Suggested ADRs:

```text
ADR-001 durable workflow state

ADR-002 event idempotency strategy

ADR-003 failure classification architecture

ADR-004 repair proposal vs direct remediation

ADR-005 sandbox isolation boundary

ADR-006 retry-budget design

ADR-007 policy-engine design

ADR-008 canary rollout strategy

ADR-009 audit-evidence architecture

ADR-010 observability and SLO model

ADR-011 Python vs Go vs Rust boundaries
```

Every ADR should contain:

```text
Status
Context
Decision
Alternatives Considered
Consequences
Risks
Revisit Conditions
```

Do NOT justify Go or Rust because they are faster or more impressive.

Only introduce another language if measurements or architecture justify the operational cost.

"Remain in Python" is a valid architectural decision.

---

# Phase 15 — Threat Model

Create:

```text
docs/security/threat-model.md
```

Analyze threats including:

```text
malicious PR
prompt injection from repository content
command injection
secret leakage
dependency poisoning
untrusted test scripts
privilege escalation
malicious generated patches
audit tampering
GitHub token compromise
cross-repository contamination
sandbox escape
```

For each threat:

```text
asset
threat
attack path
impact
mitigation
residual risk
```

Assume repository content may be malicious.

---

# Phase 16 — Observability

Implement structured logs.

Include:

```text
incident_id
repository
workflow
correlation_id
proposal_id
attempt
stage
duration
result
```

Add metrics and tracing boundaries where useful.

Avoid logging:

```text
tokens
secrets
credentials
private source unnecessarily
```

The goal is to reconstruct the lifecycle of one incident end-to-end.

---

# Phase 17 — Tests

Build a test pyramid appropriate to the repository.

Include:

```text
unit tests
contract tests
integration tests
state-machine tests
policy tests
failure-injection tests
end-to-end tests
```

Critical invariants must have explicit tests.

Examples:

```text
retry budget can never be exceeded

DENY policy can never reach deployment

human-required changes cannot auto-promote

duplicate webhook does not create duplicate incident

failed canary cannot promote

audit evidence exists for every state transition
```

---

# Phase 18 — Evidence Harness

Create a reproducible command such as:

```bash
make evidence
```

or:

```bash
python -m tools.evidence
```

It should execute representative scenarios and produce something similar to:

```text
artifacts/evidence/
├── summary.json
├── metrics.json
├── incident-trace.jsonl
├── policy-decisions.jsonl
├── retry-results.json
├── canary-results.json
└── report.md
```

The evidence harness should prove that the architecture works.

Do not rely only on diagrams and documentation.

---

# Phase 19 — Staff-Level Case Study

Create:

```text
docs/case-study.md
```

Use this structure:

# Problem

Explain why CI repair across repositories is difficult.

# Constraints

Discuss:

- untrusted code
- distributed failures
- cost
- latency
- false positives
- model uncertainty
- security
- human review

# Initial Architecture

Explain the original system.

# Failure Modes Found

Describe weaknesses discovered during engineering.

# Decisions

Reference ADRs.

# Architecture Evolution

Show how the design evolved.

# Trade-offs

Explain what was intentionally NOT built.

# Reliability Results

Show measured evidence.

# Security

Summarize trust boundaries.

# Lessons Learned

Describe what you would change at 10× scale.

---

# Phase 20 — README Upgrade

The README should communicate the system in less than two minutes.

Structure:

```text
Problem
↓
Architecture
↓
30-second demo
↓
Failure lifecycle
↓
Reliability guarantees
↓
Safety / policy model
↓
Metrics
↓
How to run
↓
Evidence
↓
Architecture decisions
```

Avoid claiming:

```text
enterprise-grade
production-ready
Staff-level
highly scalable
AI-powered
```

without evidence.

Show the evidence instead.

---

# Architecture Review Questions

Before implementing any major component, ask:

1. What failure mode are we solving?
2. Does this already exist?
3. Can the current architecture solve it?
4. Do we need another service?
5. Do we need another language?
6. What operational complexity does this introduce?
7. How will we test it?
8. How will we observe it?
9. How will we roll it back?
10. What evidence will prove it works?

If a simpler solution satisfies the requirement, choose it.

---

# Anti-Overengineering Rules

Do NOT automatically add:

- Kubernetes
- Kafka
- Redis
- microservices
- service mesh
- vector database
- Rust
- Go
- distributed consensus
- complex event sourcing

Only introduce infrastructure when an explicit requirement justifies it.

Prefer:

```text
boring technology
clear boundaries
strong tests
measurable reliability
simple operations
```

---

# Required Final Architecture

Aim for a conceptual architecture similar to:

```text
                 GitHub / CI Providers
                         │
                         ▼
                Event Ingestion Layer
                         │
                         ▼
                 Incident Manager
                         │
              ┌──────────┴───────────┐
              ▼                      ▼
     Failure Classifier        Durable State
              │
              ▼
       Repair Proposal
              │
              ▼
         Policy Engine
              │
       ┌──────┴──────┐
       │             │
      DENY         ALLOW
                     │
                     ▼
              Sandbox Runner
                     │
                     ▼
                Evaluator
                     │
               ┌─────┴─────┐
               │           │
             FAIL         PASS
               │           │
               ▼           ▼
          Retry Budget    Canary
               │           │
               ▼           ▼
           Escalation   Verification
               │           │
               └─────┬─────┘
                     ▼
                Audit Evidence
                     │
                     ▼
              SLO / Dashboard
```

---

# Implementation Strategy

Do not attempt everything in one giant change.

Work incrementally.

For every stage:

1. inspect existing implementation
2. describe the gap
3. propose the smallest architecture change
4. state trade-offs
5. implement
6. add tests
7. run tests
8. generate evidence
9. update documentation
10. create/update ADR when appropriate

Keep existing passing behavior intact.

---

# Definition of Done

Do NOT declare the project complete merely because all code compiles.

The project is complete only when we can demonstrate:

- multiple repositories can generate isolated incidents
- failures are classified with evidence
- repairs are proposals rather than uncontrolled actions
- policy gates block unsafe changes
- execution occurs through a defined sandbox boundary
- evaluation detects failed or regressive repairs
- retry loops are bounded
- canary failures prevent promotion
- uncertain/high-risk incidents escalate to humans
- every major decision produces audit evidence
- lifecycle metrics are measurable
- SLOs are documented
- representative failures can be reproduced
- architectural trade-offs are documented in ADRs
- critical invariants are covered by tests
- README and case study accurately reflect measured capabilities

---

# Final Deliverables

At the end, give me:

## 1. Architecture assessment

```text
What existed
What changed
Why
```

## 2. Staff-signal improvements

For each improvement explain which engineering capability it demonstrates:

```text
system design
reliability
operational ownership
security
trade-off reasoning
AI governance
platform engineering
observability
```

## 3. Architecture diagram

Show the final architecture.

## 4. ADR index

List all architectural decisions.

## 5. Evidence table

Use:

| Capability | Test | Evidence | Result |
|---|---|---|---|

## 6. Remaining gaps

Separate into:

```text
Must fix before real production
Useful next
Intentionally deferred
```

## 7. Language recommendation

Only after inspecting the actual architecture, tell me whether:

```text
Keep Python

Python + Go control plane

Python + Rust component

Python + Go + Rust
```

is justified.

Do not migrate languages merely for portfolio value.

## 8. Staff Engineer assessment

Rate the repository from 1–10 on:

```text
Architecture
Reliability
Failure handling
Observability
Security
Testing
Operational maturity
Decision quality
Documentation
Evidence
```

For every score below 8, tell me exactly what concrete evidence is missing.

---

# Core Principle

Optimize for:

```text
Engineering judgment + reliability + measurable evidence + controlled failure handling.
```

Not:

```text
More code + more services + more languages.
```

The desired result is a repository where a senior engineer can inspect the code, tests, ADRs, metrics, failure scenarios, and evidence and conclude:

"This engineer understands how to design, operate, constrain, evaluate, and evolve a failure-prone automation system."

Start by inspecting the current repository and producing the Phase 0 current-state assessment.

Do not begin with a rewrite.

~~~~

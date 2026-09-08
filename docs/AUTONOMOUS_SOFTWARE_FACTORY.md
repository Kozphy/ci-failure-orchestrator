# Autonomous Software Factory v0.5

This repository is evolving from a CI-failure repair orchestrator into a vendor-neutral autonomous engineering control plane.

## North-star loop

```text
Human intent
  -> model-backed structured spec
  -> deterministic spec validation
  -> task DAG
  -> cost/risk-aware model router
  -> sandboxed agent runtime
  -> independent evaluator
  -> durable evidence
  -> CI provider adapter
  -> bounded repair loop
  -> governance gate
  -> merge / deploy
  -> production feedback
```

## Implemented layers

### v0.1 — Factory kernel
- dependency-aware `FactoryTask`
- `AgentRuntime`, `Evaluator`, `GovernanceGate`
- bounded autonomous execute/evaluate/retry loop

### v0.2 — Spec engine
- machine-readable `FactorySpec` / `TaskSpec`
- deterministic `SpecCompiler`
- duplicate, dependency, risk and cycle validation

### v0.3 — Goal runtime + evidence
- `GoalDrivenFactory`
- Goal -> Spec -> DAG -> Agent -> Eval -> Repair
- per-attempt evidence recording
- runtime routing
- vendor-neutral CI contract

### v0.4 — Provider + CI integration layer
- model-backed `ModelGoalSpecProvider`
- sandboxed `ProviderCLIRuntime` for Codex/Cursor/Claude/Gemini-style CLIs
- append-only `JsonlEvidenceStore`
- GitHub Actions and CircleCI adapters over a shared CI transport contract

### v0.5 — Economics + operational telemetry
- `CostAwareModelRouter` chooses the cheapest provider that satisfies task risk
- `BudgetLedger` enforces a hard autonomous spend ceiling
- `BudgetedRuntimeRouter` combines provider routing, execution, budget enforcement and metrics
- factory metrics capture task attempts, provider selection, estimated cost and agent latency
- fail-closed behavior when no provider fits risk/budget or a runtime is missing

## Safety invariants

1. **Maker != checker.** Execution and evaluation are separate interfaces.
2. **Evidence decides completion.** Agent confidence never determines DONE.
3. **Bound retries and spend.** Attempts and estimated provider cost are hard-limited.
4. **Least privilege.** High-risk tasks remain blocked unless governance explicitly permits them.
5. **Vendor neutral.** Model, agent and CI providers live behind adapters.
6. **Fail closed.** Missing runtimes, invalid specs, unsupported risk or exhausted budget stop autonomous progress.
7. **Git remains system of record.** Specs, policies, evidence and changes remain auditable.

## Current control plane

```text
Goal
 -> ModelGoalSpecProvider
 -> FactorySpec
 -> SpecCompiler
 -> Task DAG
 -> CostAwareModelRouter
 -> BudgetedRuntimeRouter
 -> Codex / Cursor / Claude / Gemini runtime adapter
 -> Evaluator
 -> JsonlEvidenceStore
 -> GitHub Actions / CircleCI
 -> Retry or stop
 -> Risk governance
```

## Definition of DONE

```text
DONE = acceptance criteria satisfied
   AND required tests/evals pass
   AND policy allows progression
   AND required evidence exists
   AND task budget was not exceeded
```

## Next milestone — v0.6 Parallel Factory

- isolated Git worktrees per independent task
- bounded parallel scheduling from the DAG
- conflict detection before integration
- authenticated GitHub/CircleCI transports
- CI failure -> repair-agent routing
- factory-level SLO / success-rate / cost-per-task dashboards

## v1.0 target

```text
Goal -> Spec -> Plan -> Parallel Build -> Verify -> CI -> Deploy -> Observe -> RCA -> Repair -> Improve
```

# Autonomous Software Factory v0.1

This repository is evolving from a CI-failure repair orchestrator into a vendor-neutral autonomous engineering control plane.

## North-star loop

```text
Human intent
  -> executable spec
  -> task graph
  -> agent runtime
  -> independent evaluator
  -> risk gate
  -> CI / evidence
  -> repair loop
  -> merge / deploy
  -> production feedback
  -> new task
```

## v0.1 primitives

- `FactoryTask`: a goal, acceptance criteria, dependencies, risk and execution state.
- `AgentRuntime`: adapter boundary for Codex, Claude Code, Cursor, Orca or future runtimes.
- `Evaluator`: independent proof layer. An agent saying `DONE` never determines correctness.
- `GovernanceGate`: risk-based autonomy boundary.
- `AutonomousSoftwareFactory`: persistent execute -> evaluate -> retry loop with bounded attempts.

## Design invariants

1. **Maker != checker.** Agent execution and evaluation are separate interfaces.
2. **Evidence decides completion.** Tests/evals determine task completion, not model confidence.
3. **Bound retries.** Autonomous repair must stop after a configured attempt budget.
4. **Least privilege.** High-risk tasks are blocked by default.
5. **Vendor neutral.** Agent and CI providers live behind adapters instead of being hard-coded into the control plane.
6. **Git remains system of record.** Specs, tasks, evidence and policy should remain auditable.

## Existing CI repair becomes the first vertical slice

The repository's current CI failure classification, repair, approval, canary, audit, benchmark and agent-loop capabilities remain useful. They become the first production workload of the larger factory:

```text
CI failure
  -> classify
  -> RCA
  -> repair runtime
  -> evaluator
  -> governance
  -> retry or stop
```

## Next milestones

### v0.2 — Spec engine + task DAG

Natural-language goal -> structured spec -> acceptance criteria -> dependency graph.

### v0.3 — Runtime adapters

- local subprocess / test runtime
- Codex adapter
- Cursor adapter
- Orca worktree adapter

### v0.4 — CI provider adapters

Provide a common interface such as:

```python
ci.run()
ci.status()
ci.logs()
ci.retry()
```

with GitHub Actions and CircleCI implementations.

### v0.5 — Evidence and policy

Persist test, security, performance and audit evidence. Introduce policy-as-code and approval escalation.

### v0.6 — Parallel factory

Run independent tasks in isolated worktrees/sandboxes and merge only after dependency/evaluation gates pass.

### v1.0 — Closed-loop engineering

Goal -> spec -> build -> verify -> deploy -> observe -> RCA -> repair -> evolve.

## Definition of DONE

A task is not complete because an agent says it is complete.

```text
DONE = acceptance criteria satisfied
   AND required tests pass
   AND policy allows progression
   AND required evidence exists
```

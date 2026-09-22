# ADR-0001: Separate planning from execution

## Status

Accepted

## Context

Autonomous repair agents that plan and mutate in one step are hard to audit and govern.

## Decision

`Planner` / `AgentModel.generate_plan` emit `RepairPlan` only. Tool invocation, proposal application, and verification happen in later pipeline stages.

## Consequences

- Tests can swap deterministic planners without sandboxes.
- Illegal for planners to touch the working tree.

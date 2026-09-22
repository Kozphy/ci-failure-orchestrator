# ADR-0004: Evaluation gate before policy approval

## Status

Accepted

## Context

Agent self-report is insufficient for remediation success.

## Decision

`LocalEvaluator` / `EvalForgeAdapter` must produce structured `EvaluationResult` before `PolicyEngine` can `APPROVE`.

## Consequences

- Scores are optional; boolean evidence fields are required.
- Remote EvalForge remains an injectable boundary.

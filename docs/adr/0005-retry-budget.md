# ADR-0005: Bounded retry budget

## Status

Accepted

## Context

Unbounded agent loops create cost and risk without improving outcomes.

## Decision

`RetryBudget` caps attempts and stops on identical failure/patch fingerprints, policy blocks, or human requirement.

## Consequences

- Exhaustion yields actionable `HumanEscalation`, not silent spinning.

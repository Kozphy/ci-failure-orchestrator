# ADR-0006: Policy gate outcomes

## Status

Accepted

## Context

Technically green patches can still be unsafe (workflows, auth, secrets).

## Decision

`PolicyEngine` returns `APPROVE | REJECT | ESCALATE | RETRY` using proposal paths, classification, and evaluation evidence.

## Consequences

- Golden fixtures assert governance outcomes (`forbid_success`) separately from test-greenness.

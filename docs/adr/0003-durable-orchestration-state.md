# ADR-0003: Durable governed run state

## Status

Accepted

## Context

Workers crash; at-least-once delivery exists; operators need replay/explain.

## Decision

Persist governed runs and append-only events in SQLite (`SQLiteGovernedStore`), alongside existing run/idempotency stores.

## Consequences

- Local demos stay dependency-free.
- Postgres can replace the store behind `StateStore` later.

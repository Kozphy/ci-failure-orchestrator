# ADR-0008: SQL durable state and a lease-based job queue behind an HTTP API

## Status

Accepted (Phase 1 of `docs/reliability-upgrade-plan.md`).

## Context

The canonical foundation (`foundation/runner.py`) persisted run state and audit events only as
files (`runs/<id>/state.json`, `events.jsonl`) on the host that ran the CLI. That cannot serve
an HTTP API with separate worker processes: there is no shared state, no way to hand work to
another process, and no defined behaviour when a process dies mid-run. ADR-0003 anticipated
that "Postgres can replace the store behind `StateStore` later".

## Decision

1. **Implement the existing protocols, do not replace them.** `server/sql_store.py` adds
   `SqlStateStore` and `SqlAuditStore` (implementing `StateStore` / `AuditStore` from
   `foundation/durable.py`) and `MirroredEvidenceStore`. `RunPersistence` accepts injected
   stores; the runner accepts an injected `RunPersistence`. File stores remain the default, so
   the CLI and every existing reader are unchanged.
2. **One schema for PostgreSQL and SQLite** using SQLAlchemy Core. PostgreSQL in deployment,
   SQLite for local tests. Database constraints back the in-process checks: primary key on
   `runs.run_id`, unique `audit_events.event_id`, unique `(run_id, sequence)`.
3. **Evidence files stay on disk; the database mirrors them.** Every evidence write also stores
   the sanitized bytes plus SHA-256 in `evidence`, so evidence is queryable and survives loss of
   the artifacts volume. The file is still the copy existing tools read.
4. **API and execution are separate processes.** The API validates, enqueues and reads. The
   worker claims jobs with a conditional `UPDATE ... WHERE status='QUEUED'` (atomic on both
   backends without `SELECT ... FOR UPDATE`), holds a lease renewed by a heartbeat thread, and
   records the outcome only if it still owns the lease (fencing).
5. **Expired leases go to `REQUIRES_REVIEW`, not back to the queue.** A run that stopped mid-way
   has already written audit events and evidence under its run ID and may have executed tools;
   re-running it automatically could duplicate side effects. A `WORKER_LEASE_EXPIRED` audit event
   is appended to the run.
6. **Persistence failure mid-run is a review state.** If the runner reports `PERSISTENCE_ERROR`,
   the job becomes `REQUIRES_REVIEW` with the sanitized reason.

## Consequences

- Durable state, audit events and evidence survive API and worker restarts (tested by
  disposing and recreating the engine in `tests/test_server_worker.py`).
- Throughput is one run at a time per worker; scale by adding workers.
- Schema is created with `create_all`. Versioned migrations (Alembic) are required before the
  first incompatible schema change.
- The audit table is insert-only from application code but not tamper-evident; a hash chain is
  Phase 6.
- The optional `CFO_API_TOKEN` is a single shared bearer token, not RBAC (Phase 6).
- The API runs the same deterministic foundation pipeline as `foundation-run`. It does not
  check out the submitted repository; proposals are heuristic or scripted (see
  `docs/ENGINEERING.md` Limitations).

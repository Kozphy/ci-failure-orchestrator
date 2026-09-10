from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class InvocationBudget:
    """Hard limits for autonomous AI execution.

    A run must remain within every configured limit. The runtime treats a zero
    or negative limit as disabled so operators can opt into only the controls
    they can measure reliably.
    """

    max_calls: int = 20
    max_tokens: int = 100_000
    max_cost_usd: float = 5.0


@dataclass
class InvocationUsage:
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0

    def can_consume(self, *, calls: int = 1, tokens: int = 0, cost_usd: float = 0.0,
                    budget: InvocationBudget) -> bool:
        checks = (
            budget.max_calls <= 0 or self.calls + calls <= budget.max_calls,
            budget.max_tokens <= 0 or self.tokens + tokens <= budget.max_tokens,
            budget.max_cost_usd <= 0 or self.cost_usd + cost_usd <= budget.max_cost_usd,
        )
        return all(checks)

    def consume(self, *, calls: int = 1, tokens: int = 0, cost_usd: float = 0.0,
                budget: InvocationBudget) -> None:
        if not self.can_consume(calls=calls, tokens=tokens, cost_usd=cost_usd, budget=budget):
            raise RuntimeError("AI invocation budget exceeded")
        self.calls += calls
        self.tokens += tokens
        self.cost_usd += cost_usd


@dataclass
class DurableRunState:
    run_id: str
    incident_id: str
    status: str = "queued"
    step: str = "detected"
    attempts: int = 0
    max_attempts: int = 3
    usage: InvocationUsage = field(default_factory=InvocationUsage)
    payload: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
    next_run_at: float = 0.0
    lease_owner: str | None = None
    lease_until: float = 0.0
    updated_at: float = field(default_factory=time.time)

    @property
    def retry_exhausted(self) -> bool:
        return self.attempts >= self.max_attempts


class SQLiteRunStore:
    """SQLite-backed durable state, scheduling leases, and dead-letter queue.

    SQLite keeps the local/demo path dependency-free. The API intentionally
    mirrors primitives that can later be backed by Postgres plus a real queue.
    """

    def __init__(self, path: str | Path = ".ci-orchestrator/runtime.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    step TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    usage_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    last_error TEXT,
                    next_run_at REAL NOT NULL,
                    lease_owner TEXT,
                    lease_until REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_runs_due
                ON runs(status, next_run_at, lease_until);

                CREATE TABLE IF NOT EXISTS dead_letters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def _row_to_state(row: sqlite3.Row) -> DurableRunState:
        return DurableRunState(
            run_id=row["run_id"],
            incident_id=row["incident_id"],
            status=row["status"],
            step=row["step"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            usage=InvocationUsage(**json.loads(row["usage_json"])),
            payload=json.loads(row["payload_json"]),
            last_error=row["last_error"],
            next_run_at=row["next_run_at"],
            lease_owner=row["lease_owner"],
            lease_until=row["lease_until"],
            updated_at=row["updated_at"],
        )

    def save(self, state: DurableRunState) -> None:
        state.updated_at = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    incident_id=excluded.incident_id,
                    status=excluded.status,
                    step=excluded.step,
                    attempts=excluded.attempts,
                    max_attempts=excluded.max_attempts,
                    usage_json=excluded.usage_json,
                    payload_json=excluded.payload_json,
                    last_error=excluded.last_error,
                    next_run_at=excluded.next_run_at,
                    lease_owner=excluded.lease_owner,
                    lease_until=excluded.lease_until,
                    updated_at=excluded.updated_at
                """,
                (
                    state.run_id, state.incident_id, state.status, state.step,
                    state.attempts, state.max_attempts,
                    json.dumps(asdict(state.usage), sort_keys=True),
                    json.dumps(state.payload, sort_keys=True), state.last_error,
                    state.next_run_at, state.lease_owner, state.lease_until,
                    state.updated_at,
                ),
            )

    def load(self, run_id: str) -> DurableRunState | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_state(row) if row else None

    def lease_due(self, *, owner: str, now: float | None = None, lease_seconds: float = 60.0,
                  limit: int = 10) -> list[DurableRunState]:
        now = time.time() if now is None else now
        lease_until = now + lease_seconds
        leased: list[DurableRunState] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT * FROM runs
                WHERE status IN ('queued', 'retry')
                  AND next_run_at <= ?
                  AND lease_until <= ?
                ORDER BY next_run_at, updated_at
                LIMIT ?
                """,
                (now, now, limit),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE runs SET lease_owner=?, lease_until=?, status='running', updated_at=? WHERE run_id=?",
                    (owner, lease_until, now, row["run_id"]),
                )
                state = self._row_to_state(row)
                state.lease_owner = owner
                state.lease_until = lease_until
                state.status = "running"
                leased.append(state)
        return leased

    def mark_retry(self, state: DurableRunState, *, error: str, backoff_seconds: float = 30.0) -> None:
        state.attempts += 1
        state.last_error = error
        state.lease_owner = None
        state.lease_until = 0.0
        if state.retry_exhausted:
            self.dead_letter(state, reason="retry_budget_exhausted")
            return
        state.status = "retry"
        state.next_run_at = time.time() + backoff_seconds
        self.save(state)

    def dead_letter(self, state: DurableRunState, *, reason: str) -> None:
        state.status = "dead_lettered"
        state.last_error = reason
        state.lease_owner = None
        state.lease_until = 0.0
        self.save(state)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO dead_letters(run_id, reason, state_json, created_at) VALUES (?, ?, ?, ?)",
                (state.run_id, reason, json.dumps(asdict(state), sort_keys=True), time.time()),
            )

    def list_dead_letters(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id, reason, state_json, created_at FROM dead_letters ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]


class AutonomousRuntime:
    """Coordinates durable scheduling, retry/DLQ, AI budget, and approval policy."""

    def __init__(self, store: SQLiteRunStore, *, budget: InvocationBudget | None = None,
                 approval_risk_threshold: float = 0.6) -> None:
        self.store = store
        self.budget = budget or InvocationBudget()
        self.approval_risk_threshold = approval_risk_threshold

    def submit(self, state: DurableRunState) -> None:
        state.status = "queued"
        state.next_run_at = min(state.next_run_at, time.time()) if state.next_run_at else time.time()
        self.store.save(state)

    def record_ai_invocation(self, state: DurableRunState, *, tokens: int, cost_usd: float) -> None:
        state.usage.consume(tokens=tokens, cost_usd=cost_usd, budget=self.budget)
        self.store.save(state)

    def approval_required(self, *, risk_score: float, production_change: bool = False,
                          destructive_change: bool = False) -> bool:
        return (
            destructive_change
            or production_change
            or risk_score >= self.approval_risk_threshold
        )

    def complete(self, state: DurableRunState, *, step: str = "verified") -> None:
        state.status = "completed"
        state.step = step
        state.lease_owner = None
        state.lease_until = 0.0
        self.store.save(state)

    def poll(self, *, owner: str, now: float | None = None, limit: int = 10) -> Iterable[DurableRunState]:
        return self.store.lease_due(owner=owner, now=now, limit=limit)

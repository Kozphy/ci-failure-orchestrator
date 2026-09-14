"""Idempotent AgentTask delivery with a durable completion ledger.

At-least-once queues may deliver the same logical task more than once. This
module ensures the *accepted side effect* for a given ``idempotency_key`` runs
at most once, even under concurrent duplicate delivery or worker crash plus
redelivery.

Architecture::

    AgentTask(idempotency_key=...)
            ↓
    CompletionLedger.claim_or_replay
            ├─ completed → return stored result (no side effect)
            ├─ active lease held by another worker → Conflict
            └─ claim acquired / reclaimed after expired lease
                    ↓
            execute accepted side effect once
                    ↓
            ledger.complete(result)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


def derive_idempotency_key(*parts: object) -> str:
    """Derive a stable idempotency key from canonical task identity parts."""

    payload = json.dumps([str(part) for part in parts], sort_keys=False, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CompletionRecord:
    """Durable record of a claimed or completed task delivery."""

    idempotency_key: str
    status: str
    owner: str | None
    lease_until: float
    result: Any | None
    created_at: float
    completed_at: float | None


@dataclass(frozen=True)
class DeliveryOutcome(Generic[T]):
    """Result of one delivery attempt against the completion ledger."""

    idempotency_key: str
    executed: bool
    replayed: bool
    result: T
    status: str


class DeliveryConflictError(RuntimeError):
    """Raised when another worker still holds an active delivery lease."""


class SQLiteCompletionLedger:
    """SQLite-backed durable completion ledger for task idempotency keys.

    Rows are keyed by ``idempotency_key``. A successful delivery transitions
    ``started`` → ``completed`` and stores the serialized side-effect result.
    Abandoned ``started`` rows become reclaimable after ``lease_until``.
    """

    def __init__(self, path: str | Path = ".ci-orchestrator/completion-ledger.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_completions (
                    idempotency_key TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    owner TEXT,
                    lease_until REAL NOT NULL,
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    completed_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_task_completions_status
                ON task_completions(status, lease_until);
                """
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> CompletionRecord:
        result = None
        if row["result_json"] is not None:
            result = json.loads(row["result_json"])
        return CompletionRecord(
            idempotency_key=row["idempotency_key"],
            status=row["status"],
            owner=row["owner"],
            lease_until=float(row["lease_until"]),
            result=result,
            created_at=float(row["created_at"]),
            completed_at=None if row["completed_at"] is None else float(row["completed_at"]),
        )

    def get(self, idempotency_key: str) -> CompletionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_completions WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_completed(self, idempotency_key: str) -> CompletionRecord | None:
        record = self.get(idempotency_key)
        if record is None or record.status != "completed":
            return None
        return record

    def try_claim(
        self,
        idempotency_key: str,
        *,
        owner: str,
        lease_seconds: float = 30.0,
        now: float | None = None,
    ) -> CompletionRecord | None:
        """Claim a key for exclusive side-effect execution.

        Returns the claimed ``started`` record when this caller owns the lease.
        Returns ``None`` when another active lease exists. Returns a completed
        record when the key was already finished (caller must not execute).
        """

        now = time.time() if now is None else now
        lease_until = now + lease_seconds
        with self._write_lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM task_completions WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row is None:
                    conn.execute(
                        """
                        INSERT INTO task_completions (
                            idempotency_key, status, owner, lease_until,
                            result_json, created_at, completed_at
                        ) VALUES (?, 'started', ?, ?, NULL, ?, NULL)
                        """,
                        (idempotency_key, owner, lease_until, now),
                    )
                    conn.commit()
                    return CompletionRecord(
                        idempotency_key=idempotency_key,
                        status="started",
                        owner=owner,
                        lease_until=lease_until,
                        result=None,
                        created_at=now,
                        completed_at=None,
                    )

                record = self._row_to_record(row)
                if record.status == "completed":
                    conn.commit()
                    return record

                if record.lease_until > now and record.owner != owner:
                    conn.commit()
                    return None

                # Reclaim abandoned/expired started rows (worker crash path).
                conn.execute(
                    """
                    UPDATE task_completions
                    SET status = 'started',
                        owner = ?,
                        lease_until = ?,
                        result_json = NULL,
                        completed_at = NULL
                    WHERE idempotency_key = ?
                    """,
                    (owner, lease_until, idempotency_key),
                )
                conn.commit()
                return CompletionRecord(
                    idempotency_key=idempotency_key,
                    status="started",
                    owner=owner,
                    lease_until=lease_until,
                    result=None,
                    created_at=record.created_at,
                    completed_at=None,
                )

    def complete(
        self,
        idempotency_key: str,
        result: Any,
        *,
        owner: str,
        now: float | None = None,
    ) -> CompletionRecord:
        """Mark a claimed key completed and persist the side-effect result."""

        now = time.time() if now is None else now
        payload = json.dumps(result, sort_keys=True, default=str)
        with self._write_lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM task_completions WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row is None:
                    conn.rollback()
                    raise RuntimeError(f"cannot complete unclaimed key: {idempotency_key}")
                record = self._row_to_record(row)
                if record.status == "completed":
                    conn.commit()
                    return record
                if record.owner != owner:
                    conn.rollback()
                    raise DeliveryConflictError(
                        f"owner {owner!r} does not hold lease for {idempotency_key}"
                    )
                conn.execute(
                    """
                    UPDATE task_completions
                    SET status = 'completed',
                        lease_until = 0,
                        result_json = ?,
                        completed_at = ?
                    WHERE idempotency_key = ?
                    """,
                    (payload, now, idempotency_key),
                )
                conn.commit()
        completed = self.get_completed(idempotency_key)
        assert completed is not None
        return completed

    def release(self, idempotency_key: str, *, owner: str, now: float | None = None) -> None:
        """Abandon a started claim so another delivery can reclaim it."""

        now = time.time() if now is None else now
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE task_completions
                    SET lease_until = ?
                    WHERE idempotency_key = ?
                      AND owner = ?
                      AND status = 'started'
                    """,
                    (now - 1.0, idempotency_key, owner),
                )


class IdempotentTaskDeliverer:
    """Deliver an AgentTask so its accepted side effect runs at most once."""

    def __init__(
        self,
        ledger: SQLiteCompletionLedger,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 30.0,
    ) -> None:
        self.ledger = ledger
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        self.lease_seconds = lease_seconds

    def deliver(
        self,
        task: Any,
        side_effect: Callable[[Any], T],
    ) -> DeliveryOutcome[T]:
        """Run ``side_effect(task)`` at most once per ``task.idempotency_key``."""

        key = getattr(task, "idempotency_key", None)
        if not key or not isinstance(key, str):
            raise ValueError("AgentTask.idempotency_key is required")

        existing = self.ledger.get_completed(key)
        if existing is not None:
            return DeliveryOutcome(
                idempotency_key=key,
                executed=False,
                replayed=True,
                result=existing.result,  # type: ignore[arg-type]
                status="completed",
            )

        claimed = self.ledger.try_claim(
            key,
            owner=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claimed is None:
            raise DeliveryConflictError(
                f"active lease prevents duplicate execution for {key}"
            )
        if claimed.status == "completed":
            return DeliveryOutcome(
                idempotency_key=key,
                executed=False,
                replayed=True,
                result=claimed.result,  # type: ignore[arg-type]
                status="completed",
            )

        try:
            result = side_effect(task)
        except Exception:
            # Crash / failure before completion: expire lease for redelivery.
            self.ledger.release(key, owner=self.worker_id)
            raise

        self.ledger.complete(key, result, owner=self.worker_id)
        return DeliveryOutcome(
            idempotency_key=key,
            executed=True,
            replayed=False,
            result=result,
            status="completed",
        )

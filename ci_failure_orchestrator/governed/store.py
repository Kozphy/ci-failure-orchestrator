"""Lightweight durable run-state store for the governed pipeline."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Protocol


class StateStore(Protocol):
    def save_run(self, run_id: str, state: dict[str, Any]) -> None: ...

    def load_run(self, run_id: str) -> dict[str, Any] | None: ...

    def append_event(self, run_id: str, event: dict[str, Any]) -> None: ...


class SQLiteGovernedStore:
    """Local SQLite implementation suitable for tests and single-host demos."""

    def __init__(self, path: str | Path = ".ci-orchestrator/governed-runs.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS governed_runs (
                    run_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS governed_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_governed_events_run
                ON governed_events(run_id, id);
                """
            )

    def save_run(self, run_id: str, state: dict[str, Any]) -> None:
        payload = json.dumps(state, sort_keys=True, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO governed_runs(run_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (run_id, payload, time.time()),
            )

    def load_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM governed_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return None if row is None else json.loads(row["state_json"])

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO governed_events(run_id, event_json, created_at) VALUES (?, ?, ?)",
                (run_id, json.dumps(event, sort_keys=True, default=str), time.time()),
            )

    def list_events(self, run_id: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_json FROM governed_events WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return tuple(json.loads(row["event_json"]) for row in rows)

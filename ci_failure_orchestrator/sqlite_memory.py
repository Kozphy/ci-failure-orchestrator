from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .failure_memory import IncidentMemory


class SQLiteIncidentStore:
    """Persistent stdlib-backed incident store for FailureMemoryAgent."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    error_signature TEXT NOT NULL,
                    failure_class TEXT NOT NULL,
                    root_stage TEXT NOT NULL,
                    changed_files TEXT NOT NULL,
                    successful_patch_summary TEXT NOT NULL,
                    failed_patch_summaries TEXT NOT NULL,
                    affected_tests TEXT NOT NULL,
                    retries INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    regression_detected INTEGER NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )

    def add(self, incident: IncidentMemory) -> None:
        payload = (
            incident.incident_id,
            incident.error_signature,
            incident.failure_class,
            incident.root_stage,
            json.dumps(incident.changed_files),
            incident.successful_patch_summary,
            json.dumps(incident.failed_patch_summaries),
            json.dumps(incident.affected_tests),
            incident.retries,
            incident.cost_usd,
            incident.latency_ms,
            int(incident.regression_detected),
            json.dumps(incident.metadata, sort_keys=True),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO incidents (
                    incident_id, error_signature, failure_class, root_stage,
                    changed_files, successful_patch_summary, failed_patch_summaries,
                    affected_tests, retries, cost_usd, latency_ms,
                    regression_detected, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    error_signature=excluded.error_signature,
                    failure_class=excluded.failure_class,
                    root_stage=excluded.root_stage,
                    changed_files=excluded.changed_files,
                    successful_patch_summary=excluded.successful_patch_summary,
                    failed_patch_summaries=excluded.failed_patch_summaries,
                    affected_tests=excluded.affected_tests,
                    retries=excluded.retries,
                    cost_usd=excluded.cost_usd,
                    latency_ms=excluded.latency_ms,
                    regression_detected=excluded.regression_detected,
                    metadata=excluded.metadata
                """,
                payload,
            )

    def all(self) -> Iterable[IncidentMemory]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM incidents ORDER BY incident_id").fetchall()
        return tuple(
            IncidentMemory(
                incident_id=row["incident_id"],
                error_signature=row["error_signature"],
                failure_class=row["failure_class"],
                root_stage=row["root_stage"],
                changed_files=tuple(json.loads(row["changed_files"])),
                successful_patch_summary=row["successful_patch_summary"],
                failed_patch_summaries=tuple(json.loads(row["failed_patch_summaries"])),
                affected_tests=tuple(json.loads(row["affected_tests"])),
                retries=int(row["retries"]),
                cost_usd=float(row["cost_usd"]),
                latency_ms=int(row["latency_ms"]),
                regression_detected=bool(row["regression_detected"]),
                metadata=dict(json.loads(row["metadata"])),
            )
            for row in rows
        )

"""SQLite-backed persistent incident store for failure memory.

This module provides a persistent SQLite-based implementation of the incident
store for the failure memory system. It uses the standard library sqlite3 module
for dependency-free persistence and supports upsert operations for incident
updates.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .failure_memory import IncidentMemory


class SQLiteIncidentStore:
    """Persistent stdlib-backed incident store for FailureMemoryAgent.

    This store provides persistent storage for CI failure incidents using SQLite,
    with automatic schema initialization and upsert support for incident updates.
    It is suitable for production deployments where persistence across restarts
    is required.

    Attributes:
        path: Filesystem path to the SQLite database file.

    Audit Notes:
        - SQLite file corruption could lose historical incident data.
        - Upsert operations modify stored incident data.
        - Recovery: Restore from backup if database file is corrupted.
        - Evidence: All incident data is persisted with full metadata for audit.

    Engineering Notes:
        - Trade-off: SQLite adds persistence but requires file I/O and disk space.
        - Design: Upsert (ON CONFLICT DO UPDATE) allows incident updates without duplicate entries.
        - Performance: SQLite is efficient for incident storage but may need indexing for large datasets.
    """

    def __init__(self, path: str | Path) -> None:
        """Initialize the SQLite incident store.

        Args:
            path: Filesystem path to the SQLite database file. Creates file if it doesn't exist.

        Side Effects:
            - Creates the database file if it doesn't exist.
            - Initializes the incidents table schema.
        """
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Create a new SQLite connection with row factory.

        Returns:
            SQLite connection with Row factory for dict-like row access.
        """
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        """Initialize the incidents table schema.

        Creates the incidents table if it doesn't exist with columns for all
        IncidentMemory fields. Uses JSON serialization for complex fields.

        Side Effects:
            - Creates the incidents table in the SQLite database.
        """
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
        """Add or update an incident in the SQLite store.

        This method uses an upsert operation (INSERT ... ON CONFLICT DO UPDATE)
        to either insert a new incident or update an existing one with the same
        incident_id. Complex fields are serialized as JSON.

        Args:
            incident: Incident memory record to store.

        Side Effects:
            - Inserts or updates the incident in the SQLite database.
            - Serializes complex fields (tuples, dicts) as JSON.
        """
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
        """Retrieve all incidents from the SQLite store.

        Returns:
            Iterable of all IncidentMemory records stored in the database,
            ordered by incident_id.

        Side Effects:
            - Reads from the SQLite database.
            - Deserializes JSON fields (tuples, dicts) from stored data.
        """
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

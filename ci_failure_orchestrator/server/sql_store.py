"""SQL implementations of the foundation ``StateStore`` / ``AuditStore`` / ``EvidenceStore`` protocols.

They honour the same contract as the File stores in ``foundation.durable`` (the shared contract
suite in ``tests/test_durable_store_contract.py`` runs against both). Database constraints
(primary key on ``run_id``; unique ``event_id``; unique ``(run_id, sequence)``) back the
in-process checks so concurrent writers cannot fork a run's audit log.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..foundation.durable import (
    AUDIT_SCHEMA,
    AuditEvent,
    DurableEvidenceRef,
    DurableRunState,
    FileEvidenceStore,
    PersistenceError,
    UnsupportedSchemaError,
    canonical_json,
)
from ..foundation.models import utc_now
from .db import audit_events, evidence, runs


def _jsonable(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _run_row(run: DurableRunState) -> dict[str, Any]:
    return {
        "workflow_status": run.workflow_status,
        "technical_status": run.technical_status,
        "policy_outcome": run.policy_outcome,
        "current_attempt": run.current_attempt,
        "last_event_sequence": run.last_event_sequence,
        "stop_reason": run.stop_reason,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "state": _jsonable(run.to_dict()),
    }


class SqlStateStore:
    """State store backed by the ``runs`` table."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def exists(self, run_id: str) -> bool:
        """Return whether a row exists for the run.

        Raises:
            PersistenceError: If the database is unavailable.
        """
        try:
            with self.engine.connect() as conn:
                row = conn.execute(sa.select(runs.c.run_id).where(runs.c.run_id == run_id)).first()
        except SQLAlchemyError as exc:
            raise PersistenceError(f"state store unavailable: {type(exc).__name__}") from exc
        return row is not None

    def create_run(self, run: DurableRunState) -> None:
        """Insert a new run.

        Raises:
            PersistenceError: If the run already exists or the database write fails.
        """
        run.updated_at = utc_now()
        try:
            with self.engine.begin() as conn:
                conn.execute(sa.insert(runs).values(run_id=run.run_id, **_run_row(run)))
        except IntegrityError as exc:
            raise PersistenceError(f"run already exists: {run.run_id}") from exc
        except SQLAlchemyError as exc:
            raise PersistenceError(f"failed to create run: {type(exc).__name__}") from exc

    def save_run(self, run: DurableRunState) -> None:
        """Stamp ``updated_at`` and upsert the run row.

        Raises:
            PersistenceError: If the database write fails.
        """
        run.updated_at = utc_now()
        values = _run_row(run)
        try:
            with self.engine.begin() as conn:
                result = conn.execute(sa.update(runs).where(runs.c.run_id == run.run_id).values(**values))
                if result.rowcount == 0:
                    conn.execute(sa.insert(runs).values(run_id=run.run_id, **values))
        except SQLAlchemyError as exc:
            raise PersistenceError(f"failed to save run state: {type(exc).__name__}") from exc

    def load_run(self, run_id: str) -> DurableRunState:
        """Load a run's durable state.

        Raises:
            FileNotFoundError: If no run exists (same contract as ``FileStateStore``).
            PersistenceError: If the database is unavailable or the stored state is malformed.
        """
        try:
            with self.engine.connect() as conn:
                row = conn.execute(sa.select(runs.c.state).where(runs.c.run_id == run_id)).first()
        except SQLAlchemyError as exc:
            raise PersistenceError(f"state store unavailable: {type(exc).__name__}") from exc
        if row is None:
            raise FileNotFoundError(f"run not found: {run_id}")
        if not isinstance(row.state, dict):
            raise PersistenceError(f"stored state must be an object for {run_id}")
        try:
            return DurableRunState.from_dict(row.state)
        except KeyError as exc:
            raise PersistenceError(f"malformed stored state for {run_id}: missing {exc}") from exc


class SqlAuditStore:
    """Audit store backed by the ``audit_events`` table (insert-only from this class)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def latest_sequence(self, run_id: str) -> int:
        """Return the highest stored sequence for the run, or 0.

        Raises:
            PersistenceError: If the database is unavailable.
        """
        try:
            with self.engine.connect() as conn:
                return self._latest(conn, run_id)
        except SQLAlchemyError as exc:
            raise PersistenceError(f"audit store unavailable: {type(exc).__name__}") from exc

    @staticmethod
    def _latest(conn: sa.Connection, run_id: str) -> int:
        value = conn.execute(
            sa.select(sa.func.max(audit_events.c.sequence)).where(audit_events.c.run_id == run_id)
        ).scalar()
        return int(value or 0)

    def append(self, event: AuditEvent) -> None:
        """Insert an event after checking its schema, event ID uniqueness and sequence order.

        Raises:
            UnsupportedSchemaError: If the event schema is not the audit schema.
            PersistenceError: If the event ID is a duplicate, the sequence is not the next one,
                a concurrent writer won the race, or the database write fails.
        """
        if event.schema_version != AUDIT_SCHEMA:
            raise UnsupportedSchemaError(event.schema_version)
        try:
            with self.engine.begin() as conn:
                duplicate = conn.execute(
                    sa.select(audit_events.c.id).where(audit_events.c.event_id == event.event_id)
                ).first()
                if duplicate is not None:
                    raise PersistenceError(f"duplicate event_id: {event.event_id}")
                last = self._latest(conn, event.run_id)
                if event.sequence != last + 1:
                    raise PersistenceError(f"non-monotonic sequence: expected {last + 1}, got {event.sequence}")
                conn.execute(
                    sa.insert(audit_events).values(
                        run_id=event.run_id,
                        sequence=event.sequence,
                        event_id=event.event_id,
                        event_type=event.event_type,
                        timestamp=event.timestamp,
                        actor=event.actor,
                        component=event.component,
                        state_before=event.state_before,
                        state_after=event.state_after,
                        payload=_jsonable(event.to_dict()),
                    )
                )
        except IntegrityError as exc:
            raise PersistenceError(
                f"audit append conflict for {event.run_id} sequence {event.sequence}"
            ) from exc
        except SQLAlchemyError as exc:
            raise PersistenceError(f"failed to append audit event: {type(exc).__name__}") from exc

    def read_events(self, run_id: str) -> list[AuditEvent]:
        """Return the run's audit events ordered by sequence.

        Raises:
            PersistenceError: If the database is unavailable or a stored event is malformed.
        """
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    sa.select(audit_events.c.payload)
                    .where(audit_events.c.run_id == run_id)
                    .order_by(audit_events.c.sequence)
                ).all()
        except SQLAlchemyError as exc:
            raise PersistenceError(f"audit store unavailable: {type(exc).__name__}") from exc
        events: list[AuditEvent] = []
        for row in rows:
            try:
                events.append(AuditEvent.from_dict(row.payload))
            except (KeyError, TypeError, ValueError) as exc:
                raise PersistenceError(f"corrupt audit event for {run_id}") from exc
        return events


@dataclass(frozen=True)
class EvidenceRecord:
    """Metadata of one mirrored evidence document."""

    kind: str
    ref: str
    content_type: str
    sha256: str
    size_bytes: int
    written_at: str


class MirroredEvidenceStore:
    """Writes evidence files through ``FileEvidenceStore`` and mirrors the sanitized bytes into SQL.

    The file stays the primary copy for the existing CLI readers; the ``evidence`` row makes the
    same content (with its SHA-256) queryable and durable even if the artifacts volume is lost.
    """

    def __init__(self, file_store: FileEvidenceStore, engine: Engine) -> None:
        self.file_store = file_store
        self.engine = engine

    def write_json(self, run_id: str, kind: str, value: object, *, name: str | None = None) -> DurableEvidenceRef:
        """Write JSON evidence to disk, then mirror it.

        Raises:
            PersistenceError: If the file write or the database mirror fails.
        """
        ref = self.file_store.write_json(run_id, kind, value, name=name)
        self._mirror(run_id, ref)
        return ref

    def write_text(
        self,
        run_id: str,
        kind: str,
        content: str,
        *,
        name: str | None = None,
        max_chars: int | None = None,
    ) -> DurableEvidenceRef:
        """Write text evidence to disk, then mirror it.

        Raises:
            PersistenceError: If the file write or the database mirror fails.
        """
        ref = self.file_store.write_text(run_id, kind, content, name=name, max_chars=max_chars)
        self._mirror(run_id, ref)
        return ref

    def _mirror(self, run_id: str, ref: DurableEvidenceRef) -> None:
        path = self.file_store.run_root(run_id) / ref.ref
        try:
            body = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PersistenceError(f"evidence written but unreadable: {ref.ref}") from exc
        encoded = body.encode("utf-8")
        values = {
            "kind": ref.kind,
            "content_type": ref.content_type,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
            "content": body,
            "written_at": utc_now(),
        }
        try:
            with self.engine.begin() as conn:
                result = conn.execute(
                    sa.update(evidence)
                    .where(evidence.c.run_id == run_id, evidence.c.ref == ref.ref)
                    .values(**values)
                )
                if result.rowcount == 0:
                    conn.execute(sa.insert(evidence).values(run_id=run_id, ref=ref.ref, **values))
        except SQLAlchemyError as exc:
            raise PersistenceError(f"failed to mirror evidence {ref.ref}: {type(exc).__name__}") from exc


def list_evidence(engine: Engine, run_id: str) -> list[EvidenceRecord]:
    """Return metadata (not content) of a run's mirrored evidence, ordered by ref."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(
                evidence.c.kind,
                evidence.c.ref,
                evidence.c.content_type,
                evidence.c.sha256,
                evidence.c.size_bytes,
                evidence.c.written_at,
            )
            .where(evidence.c.run_id == run_id)
            .order_by(evidence.c.ref)
        ).all()
    return [EvidenceRecord(**row._asdict()) for row in rows]

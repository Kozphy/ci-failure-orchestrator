"""SQL schema and engine helpers for durable run state.

The same SQLAlchemy Core schema runs on PostgreSQL (deployment) and SQLite (local tests).
Schema creation uses ``create_all``; versioned migrations are a documented follow-up.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, make_url

SCHEMA_VERSION = "server.db.v1"

metadata = sa.MetaData()

_JSON = sa.JSON().with_variant(JSONB(), "postgresql")
_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
_TS = sa.DateTime(timezone=True)

runs = sa.Table(
    "runs",
    metadata,
    sa.Column("run_id", sa.String(64), primary_key=True),
    sa.Column("workflow_status", sa.String(64), nullable=False, index=True),
    sa.Column("technical_status", sa.String(32)),
    sa.Column("policy_outcome", sa.String(32)),
    sa.Column("current_attempt", sa.Integer, nullable=False, default=0),
    sa.Column("last_event_sequence", sa.Integer, nullable=False, default=0),
    sa.Column("stop_reason", sa.Text),
    sa.Column("created_at", sa.String(64), nullable=False),
    sa.Column("updated_at", sa.String(64), nullable=False),
    sa.Column("state", _JSON, nullable=False),
)

audit_events = sa.Table(
    "audit_events",
    metadata,
    sa.Column("id", _PK, primary_key=True, autoincrement=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("sequence", sa.Integer, nullable=False),
    sa.Column("event_id", sa.String(64), nullable=False, unique=True),
    sa.Column("event_type", sa.String(64), nullable=False),
    sa.Column("timestamp", sa.String(64), nullable=False),
    sa.Column("actor", sa.String(128), nullable=False),
    sa.Column("component", sa.String(64), nullable=False),
    sa.Column("state_before", sa.String(64)),
    sa.Column("state_after", sa.String(64)),
    sa.Column("payload", _JSON, nullable=False),
    sa.UniqueConstraint("run_id", "sequence", name="uq_audit_run_sequence"),
)

evidence = sa.Table(
    "evidence",
    metadata,
    sa.Column("id", _PK, primary_key=True, autoincrement=True),
    sa.Column("run_id", sa.String(64), nullable=False, index=True),
    sa.Column("kind", sa.String(64), nullable=False),
    sa.Column("ref", sa.String(512), nullable=False),
    sa.Column("content_type", sa.String(64), nullable=False),
    sa.Column("sha256", sa.String(64), nullable=False),
    sa.Column("size_bytes", sa.Integer, nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("written_at", sa.String(64), nullable=False),
    sa.UniqueConstraint("run_id", "ref", name="uq_evidence_run_ref"),
)

jobs = sa.Table(
    "jobs",
    metadata,
    sa.Column("job_id", sa.String(64), primary_key=True),
    sa.Column("run_id", sa.String(64), nullable=False, unique=True),
    sa.Column("status", sa.String(32), nullable=False, index=True),
    sa.Column("workflow", sa.String(255), nullable=False),
    sa.Column("repository", sa.String(255), nullable=False, default=""),
    sa.Column("payload", _JSON, nullable=False),
    sa.Column("request_sha256", sa.String(64), nullable=False),
    sa.Column("idempotency_key", sa.String(255), unique=True),
    sa.Column("claim_count", sa.Integer, nullable=False, default=0),
    sa.Column("lease_owner", sa.String(128)),
    sa.Column("lease_expires_at", _TS),
    sa.Column("workflow_status", sa.String(64)),
    sa.Column("failure_class", sa.String(64)),
    sa.Column("error", sa.Text),
    sa.Column("created_at", _TS, nullable=False),
    sa.Column("updated_at", _TS, nullable=False),
    sa.Column("started_at", _TS),
    sa.Column("finished_at", _TS),
)


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Treat naive datetimes (SQLite drops tzinfo) as UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def create_engine_from_url(url: str) -> Engine:
    """Create an engine with pool and timeout settings suited to the backend.

    SQLite gets WAL mode and a busy timeout so the API and worker can share one file.
    PostgreSQL gets ``pool_pre_ping`` and a short connect timeout so readiness fails fast.

    Args:
        url: SQLAlchemy database URL.

    Returns:
        The configured engine. No connection is opened yet.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        database = parsed.database or ""
        if database and database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        engine = sa.create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @sa.event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver callback
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return engine
    connect_args = {"connect_timeout": 5} if parsed.get_backend_name() == "postgresql" else {}
    return sa.create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    """Create any missing tables."""
    metadata.create_all(engine, checkfirst=True)


def check_database(engine: Engine) -> None:
    """Run ``SELECT 1`` and verify the schema exists; raise ``SQLAlchemyError`` on failure."""
    with engine.connect() as conn:
        conn.execute(sa.text("SELECT 1"))
        conn.execute(sa.select(jobs.c.job_id).limit(1))

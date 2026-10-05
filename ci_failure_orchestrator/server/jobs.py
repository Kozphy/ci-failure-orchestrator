"""Database-backed job queue with leases, fencing and idempotent submission.

Claiming uses a conditional ``UPDATE ... WHERE status = 'QUEUED'`` and checks the row count, so
it is atomic on both PostgreSQL and SQLite without ``SELECT ... FOR UPDATE``. Completion and
lease renewal are fenced on ``lease_owner``: a worker whose lease was recovered cannot
overwrite the recovered outcome.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from ..foundation.durable import canonical_json
from ..foundation.models import new_id
from .db import as_utc, jobs, utcnow


class JobStatus(str, Enum):
    """Processing status of a queued run (not the run's governance outcome)."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.REQUIRES_REVIEW})


class IdempotencyConflictError(ValueError):
    """The idempotency key was already used with a different request body."""


@dataclass(frozen=True)
class JobRecord:
    """One row of the ``jobs`` table."""

    job_id: str
    run_id: str
    status: JobStatus
    workflow: str
    repository: str
    payload: dict[str, Any]
    request_sha256: str
    idempotency_key: str | None
    claim_count: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    workflow_status: str | None
    failure_class: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_row(cls, row: Any) -> JobRecord:
        """Build a record from a SQLAlchemy row of ``jobs``."""
        data = row._asdict()
        for key in ("lease_expires_at", "created_at", "updated_at", "started_at", "finished_at"):
            data[key] = as_utc(data[key])
        data["status"] = JobStatus(data["status"])
        return cls(**data)


@dataclass(frozen=True)
class EnqueueResult:
    """A job plus whether this call created it (False when an idempotent replay)."""

    job: JobRecord
    created: bool


def request_digest(payload: dict[str, Any]) -> str:
    """Return the SHA-256 of the canonical JSON form of a request payload."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class JobQueue:
    """Queue operations over the ``jobs`` table."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def enqueue(
        self,
        payload: dict[str, Any],
        *,
        workflow: str,
        repository: str = "",
        idempotency_key: str | None = None,
    ) -> EnqueueResult:
        """Insert a QUEUED job with a new run ID, or return the job already stored for the key.

        Args:
            payload: Failure event payload passed to the foundation runner.
            workflow: CI workflow name, stored for listing and filtering.
            repository: Repository slug, stored for listing.
            idempotency_key: Optional client key; replays with the same body return the same job.

        Returns:
            The job and whether it was created by this call.

        Raises:
            IdempotencyConflictError: If the key was used with a different payload.
        """
        digest = request_digest(payload)
        if idempotency_key:
            existing = self._by_key(idempotency_key)
            if existing is not None:
                return self._replay(existing, digest)
        now = utcnow()
        job_id = new_id("job")
        values = {
            "job_id": job_id,
            "run_id": new_id("run"),
            "status": JobStatus.QUEUED.value,
            "workflow": workflow,
            "repository": repository,
            "payload": payload,
            "request_sha256": digest,
            "idempotency_key": idempotency_key,
            "claim_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self.engine.begin() as conn:
                conn.execute(sa.insert(jobs).values(**values))
        except IntegrityError:
            if idempotency_key:
                existing = self._by_key(idempotency_key)
                if existing is not None:
                    return self._replay(existing, digest)
            raise
        job = self.get(job_id)
        assert job is not None
        return EnqueueResult(job=job, created=True)

    @staticmethod
    def _replay(existing: JobRecord, digest: str) -> EnqueueResult:
        if existing.request_sha256 != digest:
            raise IdempotencyConflictError("idempotency key reused with a different request body")
        return EnqueueResult(job=existing, created=False)

    def _by_key(self, key: str) -> JobRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(sa.select(jobs).where(jobs.c.idempotency_key == key)).first()
        return JobRecord.from_row(row) if row is not None else None

    def get(self, job_id: str) -> JobRecord | None:
        """Return a job by ID, or None."""
        with self.engine.connect() as conn:
            row = conn.execute(sa.select(jobs).where(jobs.c.job_id == job_id)).first()
        return JobRecord.from_row(row) if row is not None else None

    def get_by_run(self, run_id: str) -> JobRecord | None:
        """Return the job that owns a run ID, or None."""
        with self.engine.connect() as conn:
            row = conn.execute(sa.select(jobs).where(jobs.c.run_id == run_id)).first()
        return JobRecord.from_row(row) if row is not None else None

    def list_jobs(self, *, status: JobStatus | None = None, limit: int = 50) -> list[JobRecord]:
        """Return the newest jobs first, optionally filtered by status."""
        query = sa.select(jobs).order_by(jobs.c.created_at.desc(), jobs.c.job_id.desc()).limit(limit)
        if status is not None:
            query = query.where(jobs.c.status == status.value)
        with self.engine.connect() as conn:
            return [JobRecord.from_row(row) for row in conn.execute(query).all()]

    def claim(self, worker_id: str, lease_seconds: int, *, now: datetime | None = None) -> JobRecord | None:
        """Atomically move the oldest QUEUED job to RUNNING under a lease owned by ``worker_id``.

        Returns:
            The claimed job, or None if no job could be claimed.
        """
        now = now or utcnow()
        with self.engine.connect() as conn:
            candidates = conn.execute(
                sa.select(jobs.c.job_id)
                .where(jobs.c.status == JobStatus.QUEUED.value)
                .order_by(jobs.c.created_at, jobs.c.job_id)
                .limit(10)
            ).scalars().all()
        for job_id in candidates:
            with self.engine.begin() as conn:
                result = conn.execute(
                    sa.update(jobs)
                    .where(jobs.c.job_id == job_id, jobs.c.status == JobStatus.QUEUED.value)
                    .values(
                        status=JobStatus.RUNNING.value,
                        lease_owner=worker_id,
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                        claim_count=jobs.c.claim_count + 1,
                        started_at=now,
                        updated_at=now,
                    )
                )
            if result.rowcount == 1:
                return self.get(job_id)
        return None

    def renew_lease(self, job_id: str, worker_id: str, lease_seconds: int, *, now: datetime | None = None) -> bool:
        """Extend a RUNNING job's lease; returns False if ``worker_id`` no longer owns it."""
        now = now or utcnow()
        with self.engine.begin() as conn:
            result = conn.execute(
                sa.update(jobs)
                .where(
                    jobs.c.job_id == job_id,
                    jobs.c.status == JobStatus.RUNNING.value,
                    jobs.c.lease_owner == worker_id,
                )
                .values(lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now)
            )
        return result.rowcount == 1

    def complete(
        self,
        job_id: str,
        worker_id: str,
        status: JobStatus,
        *,
        workflow_status: str | None = None,
        failure_class: str | None = None,
        error: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Record a terminal status if ``worker_id`` still owns the RUNNING job.

        Returns:
            True if the update applied; False if the lease was lost (fenced out).

        Raises:
            ValueError: If ``status`` is not terminal.
        """
        if status not in TERMINAL_JOB_STATUSES:
            raise ValueError(f"not a terminal job status: {status}")
        now = now or utcnow()
        with self.engine.begin() as conn:
            result = conn.execute(
                sa.update(jobs)
                .where(
                    jobs.c.job_id == job_id,
                    jobs.c.status == JobStatus.RUNNING.value,
                    jobs.c.lease_owner == worker_id,
                )
                .values(
                    status=status.value,
                    workflow_status=workflow_status,
                    failure_class=failure_class,
                    error=error,
                    lease_expires_at=None,
                    finished_at=now,
                    updated_at=now,
                )
            )
        return result.rowcount == 1

    def recover_stale(self, *, now: datetime | None = None) -> list[JobRecord]:
        """Move RUNNING jobs whose lease expired to REQUIRES_REVIEW.

        A run that stopped mid-way may have written partial audit events and evidence under its
        run ID, so it is not re-executed automatically.

        Returns:
            The jobs moved by this call.
        """
        now = now or utcnow()
        with self.engine.connect() as conn:
            stale = conn.execute(
                sa.select(jobs.c.job_id, jobs.c.lease_owner).where(
                    jobs.c.status == JobStatus.RUNNING.value, jobs.c.lease_expires_at < now
                )
            ).all()
        recovered: list[JobRecord] = []
        for job_id, owner in stale:
            with self.engine.begin() as conn:
                result = conn.execute(
                    sa.update(jobs)
                    .where(
                        jobs.c.job_id == job_id,
                        jobs.c.status == JobStatus.RUNNING.value,
                        jobs.c.lease_expires_at < now,
                    )
                    .values(
                        status=JobStatus.REQUIRES_REVIEW.value,
                        error=f"worker lease expired before completion (owner={owner})",
                        lease_expires_at=None,
                        finished_at=now,
                        updated_at=now,
                    )
                )
            if result.rowcount == 1:
                job = self.get(job_id)
                if job is not None:
                    recovered.append(job)
        return recovered

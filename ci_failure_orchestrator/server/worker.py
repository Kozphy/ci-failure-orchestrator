"""Background worker: claims queued jobs and runs them through ``AgentExecutionFoundation``.

Each job runs with SQL-backed state and audit stores and mirrored evidence. A heartbeat thread
renews the job lease while the run executes; if the worker dies, the lease expires and the next
worker tick moves the job to REQUIRES_REVIEW instead of silently re-running it. Start with::

    python -m ci_failure_orchestrator.server.worker
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable
from enum import Enum

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from ..foundation.durable import (
    AUDIT_SCHEMA,
    AuditEvent,
    AuditEventType,
    FileEvidenceStore,
    PersistenceError,
)
from ..foundation.models import FailureEvent, new_id, utc_now
from ..foundation.persistence import RunPersistence
from ..foundation.results import FoundationResult
from ..foundation.runner import AgentExecutionFoundation
from ..foundation.sanitization import sanitize_text
from .db import create_engine_from_url, init_db
from .jobs import JobQueue, JobRecord, JobStatus
from .logs import configure_logging, log_event
from .settings import ServerSettings, redact_database_url
from .sql_store import MirroredEvidenceStore, SqlAuditStore, SqlStateStore

logger = logging.getLogger("ci_failure_orchestrator.server.worker")

FoundationFactory = Callable[[RunPersistence, ServerSettings], AgentExecutionFoundation]


class TickOutcome(str, Enum):
    """What one worker iteration did."""

    IDLE = "IDLE"
    PROCESSED = "PROCESSED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


def default_foundation_factory(persistence: RunPersistence, settings: ServerSettings) -> AgentExecutionFoundation:
    """Build the same foundation ``foundation-run`` uses, wired to the given persistence."""
    return AgentExecutionFoundation(artifacts_root=settings.artifacts_root, persistence=persistence)


def _safe_error(exc: BaseException) -> str:
    return sanitize_text(f"{type(exc).__name__}: {exc}")[0][:2000]


class _LeaseHeartbeat:
    """Renews a job lease every ``lease_seconds / 3`` until stopped."""

    def __init__(self, queue: JobQueue, job_id: str, worker_id: str, lease_seconds: int) -> None:
        self._queue = queue
        self._job_id = job_id
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"lease-{job_id}", daemon=True)
        self.lost = False

    def __enter__(self) -> None:
        self._thread.start()

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        interval = max(self._lease_seconds / 3.0, 0.5)
        while not self._stop.wait(interval):
            try:
                if not self._queue.renew_lease(self._job_id, self._worker_id, self._lease_seconds):
                    self.lost = True
                    log_event(logger, "lease_lost", level=logging.WARNING, job_id=self._job_id)
                    return
            except SQLAlchemyError as exc:
                log_event(
                    logger, "lease_renew_failed", level=logging.WARNING, job_id=self._job_id, error_type=type(exc).__name__
                )


class Worker:
    """Polls the job queue and executes runs one at a time."""

    def __init__(
        self,
        engine: Engine,
        settings: ServerSettings,
        *,
        foundation_factory: FoundationFactory = default_foundation_factory,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.queue = JobQueue(engine)
        self.state_store = SqlStateStore(engine)
        self.audit_store = SqlAuditStore(engine)
        self.foundation_factory = foundation_factory

    def tick(self) -> TickOutcome:
        """Recover stale leases, then claim and process at most one job.

        Storage outages are logged and reported instead of raised so the loop keeps running.
        """
        try:
            for job in self.queue.recover_stale():
                self._record_lease_expiry(job)
            job = self.queue.claim(self.settings.worker_id, self.settings.lease_seconds)
            if job is None:
                return TickOutcome.IDLE
            self.process(job)
            return TickOutcome.PROCESSED
        except (SQLAlchemyError, PersistenceError) as exc:
            log_event(logger, "storage_unavailable", level=logging.ERROR, error_type=type(exc).__name__)
            return TickOutcome.STORAGE_UNAVAILABLE

    def process(self, job: JobRecord) -> bool:
        """Run one claimed job and record its terminal status.

        Returns:
            True if the outcome was recorded; False if the lease was lost first (fenced out).
        """
        log_event(logger, "job_started", job_id=job.job_id, run_id=job.run_id, claim=job.claim_count)
        started = time.perf_counter()
        persistence = RunPersistence(
            self.settings.artifacts_root,
            actor=self.settings.worker_id,
            state_store=self.state_store,
            audit_store=self.audit_store,
            evidence_store=MirroredEvidenceStore(FileEvidenceStore(self.settings.artifacts_root), self.engine),
        )
        status = JobStatus.COMPLETED
        workflow_status: str | None = None
        failure_class: str | None = None
        error: str | None = None
        with _LeaseHeartbeat(self.queue, job.job_id, self.settings.worker_id, self.settings.lease_seconds):
            try:
                foundation = self.foundation_factory(persistence, self.settings)
                event = FailureEvent.from_dict(dict(job.payload), run_id=job.run_id)
                result: FoundationResult = foundation.run(event)
                workflow_status = result.workflow_status or result.status.value
                if result.run.classification is not None:
                    failure_class = result.run.classification.category
                if "PERSISTENCE_ERROR" in {workflow_status, getattr(result.run, "workflow_status", None)}:
                    # Durable state may be partial; an operator must inspect before anything else acts on it.
                    status = JobStatus.REQUIRES_REVIEW
                    workflow_status = "PERSISTENCE_ERROR"
                    error = sanitize_text(result.run.stop_reason or "persistence error")[0][:2000]
            except Exception as exc:  # noqa: BLE001 - any run failure becomes a recorded FAILED job
                status = JobStatus.FAILED
                error = _safe_error(exc)
        recorded = self.queue.complete(
            job.job_id,
            self.settings.worker_id,
            status,
            workflow_status=workflow_status,
            failure_class=failure_class,
            error=error,
        )
        log_event(
            logger,
            "job_finished" if recorded else "job_fenced",
            level=logging.INFO if recorded else logging.WARNING,
            job_id=job.job_id,
            run_id=job.run_id,
            job_status=status.value,
            workflow_status=workflow_status,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return recorded

    def _record_lease_expiry(self, job: JobRecord) -> None:
        log_event(logger, "lease_expired", level=logging.WARNING, job_id=job.job_id, run_id=job.run_id)
        try:
            state = self.state_store.load_run(job.run_id)
        except FileNotFoundError:
            return
        sequence = self.audit_store.latest_sequence(job.run_id) + 1
        self.audit_store.append(
            AuditEvent(
                schema_version=AUDIT_SCHEMA,
                event_id=new_id("evt"),
                run_id=job.run_id,
                sequence=sequence,
                timestamp=utc_now(),
                event_type=AuditEventType.WORKER_LEASE_EXPIRED.value,
                actor=self.settings.worker_id,
                component="server.worker",
                state_before=state.workflow_status,
                state_after=state.workflow_status,
                metadata={"job_id": job.job_id, "previous_owner": job.lease_owner or "", "action": "REQUIRES_REVIEW"},
            )
        )
        state.last_event_sequence = sequence
        state.stop_reason = "worker_lease_expired"
        self.state_store.save_run(state)

    def run_forever(self, stop: threading.Event) -> None:
        """Tick until ``stop`` is set, sleeping when idle and backing off on storage errors."""
        backoff = self.settings.poll_seconds
        while not stop.is_set():
            outcome = self.tick()
            if outcome is TickOutcome.PROCESSED:
                backoff = self.settings.poll_seconds
                continue
            if outcome is TickOutcome.STORAGE_UNAVAILABLE:
                backoff = min(backoff * 2, 30.0)
            else:
                backoff = self.settings.poll_seconds
            stop.wait(backoff)


def _wait_for_schema(engine: Engine, stop: threading.Event, attempts: int = 30) -> bool:
    delay = 1.0
    for _ in range(attempts):
        try:
            init_db(engine)
            return True
        except SQLAlchemyError as exc:
            log_event(logger, "database_not_ready", level=logging.WARNING, error_type=type(exc).__name__)
            if stop.wait(delay):
                return False
            delay = min(delay * 2, 10.0)
    return False


def main() -> int:
    """Worker entry point; exits on SIGTERM or SIGINT after the current job finishes."""
    configure_logging()
    settings = ServerSettings.from_env()
    log_event(logger, "worker_starting", worker_id=settings.worker_id, database=redact_database_url(settings.database_url))
    engine = create_engine_from_url(settings.database_url)
    stop = threading.Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        log_event(logger, "worker_stopping", signal=signum)
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    if not _wait_for_schema(engine, stop):
        log_event(logger, "worker_gave_up_waiting_for_database", level=logging.ERROR)
        return 1
    Worker(engine, settings).run_forever(stop)
    engine.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

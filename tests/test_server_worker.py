"""Worker reliability: restart durability, crash recovery, lease fencing, failure injection."""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from ci_failure_orchestrator.foundation.persistence import (  # noqa: E402
    AuditEventType,
    PersistenceError,
    RunPersistence,
)
from ci_failure_orchestrator.foundation.runner import AgentExecutionFoundation  # noqa: E402
from ci_failure_orchestrator.server.db import create_engine_from_url, init_db, utcnow  # noqa: E402
from ci_failure_orchestrator.server.jobs import JobQueue, JobStatus  # noqa: E402
from ci_failure_orchestrator.server.settings import ServerSettings  # noqa: E402
from ci_failure_orchestrator.server.sql_store import SqlAuditStore, SqlStateStore  # noqa: E402
from ci_failure_orchestrator.server.worker import TickOutcome, Worker, default_foundation_factory  # noqa: E402

FAILURE = {
    "workflow": "ci",
    "job": "test",
    "failed_step": "pytest",
    "message": "AssertionError: expected True got False",
    "changed_paths": ["src/app.py"],
    "log_excerpt": "FAILED tests/test_app.py::test_login",
}


@pytest.fixture
def settings(tmp_path: Path) -> ServerSettings:
    return ServerSettings(
        database_url=f"sqlite:///{tmp_path / 'worker.db'}",
        artifacts_root=tmp_path / "artifacts",
        worker_id="worker-a",
        lease_seconds=60,
        poll_seconds=0.05,
    )


@pytest.fixture
def engine(settings: ServerSettings):
    eng = create_engine_from_url(settings.database_url)
    init_db(eng)
    yield eng
    eng.dispose()


def _enqueue(engine, **overrides):
    return JobQueue(engine).enqueue({**FAILURE, **overrides}, workflow="ci").job


def test_state_survives_engine_restart(settings: ServerSettings, engine):
    job = _enqueue(engine)
    assert Worker(engine, settings).tick() is TickOutcome.PROCESSED
    events_before = [e.to_dict() for e in SqlAuditStore(engine).read_events(job.run_id)]
    engine.dispose()

    restarted = create_engine_from_url(settings.database_url)
    try:
        reloaded_job = JobQueue(restarted).get(job.job_id)
        state = SqlStateStore(restarted).load_run(job.run_id)
        events_after = [e.to_dict() for e in SqlAuditStore(restarted).read_events(job.run_id)]
    finally:
        restarted.dispose()
    assert reloaded_job.status is JobStatus.COMPLETED
    assert state.workflow_status in {"APPROVED", "AWAITING_HUMAN"}
    assert events_after == events_before
    assert state.last_event_sequence == len(events_after)


def test_crashed_worker_lease_moves_job_to_requires_review_and_is_fenced(settings: ServerSettings, engine):
    queue = JobQueue(engine)
    job = _enqueue(engine)
    # worker-a claims the job, writes partial progress, then "crashes" (never completes).
    claimed = queue.claim("worker-a", lease_seconds=60, now=utcnow() - timedelta(seconds=120))
    assert claimed is not None and claimed.job_id == job.job_id
    partial = RunPersistence(
        settings.artifacts_root, actor="worker-a", state_store=SqlStateStore(engine), audit_store=SqlAuditStore(engine)
    )
    partial.start_run(job.run_id)

    survivor = ServerSettings(**{**settings.__dict__, "worker_id": "worker-b"})
    assert Worker(engine, survivor).tick() is TickOutcome.IDLE

    recovered = queue.get(job.job_id)
    assert recovered.status is JobStatus.REQUIRES_REVIEW
    assert "lease expired" in (recovered.error or "")
    assert recovered.claim_count == 1, "a partially executed run must not be re-run automatically"

    events = SqlAuditStore(engine).read_events(job.run_id)
    assert [e.event_type for e in events] == ["RUN_CREATED", AuditEventType.WORKER_LEASE_EXPIRED.value]
    assert SqlStateStore(engine).load_run(job.run_id).stop_reason == "worker_lease_expired"

    # The crashed worker comes back and tries to report: fencing rejects it.
    assert queue.complete(job.job_id, "worker-a", JobStatus.COMPLETED, workflow_status="APPROVED") is False
    assert queue.get(job.job_id).status is JobStatus.REQUIRES_REVIEW


def test_heartbeat_keeps_long_run_from_being_recovered(settings: ServerSettings, engine):
    short = ServerSettings(**{**settings.__dict__, "lease_seconds": 1})
    queue = JobQueue(engine)
    job = _enqueue(engine)
    recovered_during_run: list = []

    def slow_factory(persistence: RunPersistence, cfg: ServerSettings) -> AgentExecutionFoundation:
        foundation = default_foundation_factory(persistence, cfg)
        inner_run = foundation.run

        def run(event):
            time.sleep(2.0)
            recovered_during_run.extend(queue.recover_stale())
            return inner_run(event)

        foundation.run = run  # type: ignore[method-assign]
        return foundation

    assert Worker(engine, short, foundation_factory=slow_factory).tick() is TickOutcome.PROCESSED
    assert recovered_during_run == []
    assert queue.get(job.job_id).status is JobStatus.COMPLETED


def test_concurrent_claims_never_double_assign(engine):
    queue = JobQueue(engine)
    job_ids = {_enqueue(engine).job_id for _ in range(4)}
    claims: list[str] = []
    lock = threading.Lock()

    def claimer(worker_id: str) -> None:
        while True:
            job = JobQueue(engine).claim(worker_id, lease_seconds=60)
            if job is None:
                return
            with lock:
                claims.append(job.job_id)

    threads = [threading.Thread(target=claimer, args=(f"w{i}",)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(claims) == sorted(job_ids)
    assert all(job.status is JobStatus.RUNNING for job in queue.list_jobs())


def test_tool_failure_inside_run_is_recorded_as_failed_with_redacted_error(settings: ServerSettings, engine):
    secret = "ghp_" + "B" * 36

    def exploding_factory(persistence, cfg):
        raise RuntimeError(f"tool crashed while using token {secret}")

    job = _enqueue(engine)
    assert Worker(engine, settings, foundation_factory=exploding_factory).tick() is TickOutcome.PROCESSED
    failed = JobQueue(engine).get(job.job_id)
    assert failed.status is JobStatus.FAILED
    assert failed.error.startswith("RuntimeError: tool crashed")
    assert secret not in failed.error


class _FailAfter:
    """Audit store wrapper that raises after ``n`` successful appends (database outage mid-run)."""

    def __init__(self, inner, n: int) -> None:
        self.inner = inner
        self.remaining = n

    def append(self, event):
        if self.remaining <= 0:
            raise PersistenceError("audit store unavailable: OperationalError")
        self.remaining -= 1
        self.inner.append(event)

    def read_events(self, run_id):
        return self.inner.read_events(run_id)

    def latest_sequence(self, run_id):
        return self.inner.latest_sequence(run_id)


def test_database_outage_mid_run_requires_review(settings: ServerSettings, engine):
    def flaky_factory(persistence: RunPersistence, cfg: ServerSettings) -> AgentExecutionFoundation:
        persistence.audit_store = _FailAfter(persistence.audit_store, 3)
        return default_foundation_factory(persistence, cfg)

    job = _enqueue(engine)
    Worker(engine, settings, foundation_factory=flaky_factory).tick()
    record = JobQueue(engine).get(job.job_id)
    assert record.status is JobStatus.REQUIRES_REVIEW
    assert record.workflow_status == "PERSISTENCE_ERROR"
    assert len(SqlAuditStore(engine).read_events(job.run_id)) == 3


def test_tick_reports_storage_unavailable_instead_of_crashing(tmp_path: Path, settings: ServerSettings):
    db_dir = tmp_path / "not-a-db"
    db_dir.mkdir()
    broken = create_engine_from_url(f"sqlite:///{db_dir}")
    try:
        assert Worker(broken, settings).tick() is TickOutcome.STORAGE_UNAVAILABLE
    finally:
        broken.dispose()


def test_run_forever_stops_on_signal_event(settings: ServerSettings, engine):
    _enqueue(engine)
    stop = threading.Event()
    worker = Worker(engine, settings)
    thread = threading.Thread(target=worker.run_forever, args=(stop,))
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline and JobQueue(engine).list_jobs(status=JobStatus.COMPLETED) == []:
        time.sleep(0.05)
    stop.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(JobQueue(engine).list_jobs(status=JobStatus.COMPLETED)) == 1

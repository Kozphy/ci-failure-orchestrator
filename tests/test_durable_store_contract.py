"""One contract for every StateStore / AuditStore implementation (File, SQLite, optional PostgreSQL).

Set ``TEST_DATABASE_URL=postgresql+psycopg://...`` to include PostgreSQL.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from ci_failure_orchestrator.foundation import AgentExecutionFoundation, FailureEvent, RunStatus  # noqa: E402
from ci_failure_orchestrator.foundation.models import new_id, utc_now  # noqa: E402
from ci_failure_orchestrator.foundation.persistence import (  # noqa: E402
    AUDIT_SCHEMA,
    DURABLE_SCHEMA,
    AuditEvent,
    DurableRunState,
    FileAuditStore,
    FileEvidenceStore,
    FileStateStore,
    PersistenceError,
    RunPersistence,
    UnsupportedSchemaError,
)
from ci_failure_orchestrator.server.db import create_engine_from_url, init_db  # noqa: E402
from ci_failure_orchestrator.server.sql_store import (  # noqa: E402
    MirroredEvidenceStore,
    SqlAuditStore,
    SqlStateStore,
    list_evidence,
)

BACKENDS = ["file", "sqlite"] + (["postgres"] if os.environ.get("TEST_DATABASE_URL") else [])


@pytest.fixture(params=BACKENDS)
def stores(request, tmp_path: Path):
    """Yield (backend, state_store, audit_store, evidence_store, engine-or-None)."""
    if request.param == "file":
        yield (
            "file",
            FileStateStore(tmp_path),
            FileAuditStore(tmp_path),
            FileEvidenceStore(tmp_path),
            None,
        )
        return
    url = os.environ["TEST_DATABASE_URL"] if request.param == "postgres" else f"sqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_engine_from_url(url)
    init_db(engine)
    yield (
        request.param,
        SqlStateStore(engine),
        SqlAuditStore(engine),
        MirroredEvidenceStore(FileEvidenceStore(tmp_path), engine),
        engine,
    )
    engine.dispose()


def _state(run_id: str, **overrides) -> DurableRunState:
    return DurableRunState(schema_version=DURABLE_SCHEMA, run_id=run_id, workflow_status="RECEIVED", **overrides)


def _event(run_id: str, sequence: int, **overrides) -> AuditEvent:
    data = dict(
        schema_version=AUDIT_SCHEMA,
        event_id=new_id("evt"),
        run_id=run_id,
        sequence=sequence,
        timestamp=utc_now(),
        event_type="RUN_CREATED",
        actor="test",
        component="contract",
        state_before=None,
        state_after="RECEIVED",
        metadata={"n": sequence},
    )
    data.update(overrides)
    return AuditEvent(**data)


def test_state_roundtrip_and_existence(stores):
    _, state_store, _, _, _ = stores
    run_id = new_id("run")
    assert state_store.exists(run_id) is False
    state_store.create_run(_state(run_id, current_attempt=2, evidence_index={"plan": "plans/plan-001.json"}))
    assert state_store.exists(run_id) is True
    loaded = state_store.load_run(run_id)
    assert loaded.run_id == run_id
    assert loaded.current_attempt == 2
    assert loaded.evidence_index == {"plan": "plans/plan-001.json"}


def test_create_twice_is_rejected(stores):
    _, state_store, _, _, _ = stores
    run_id = new_id("run")
    state_store.create_run(_state(run_id))
    with pytest.raises(PersistenceError):
        state_store.create_run(_state(run_id))


def test_missing_run_raises_file_not_found(stores):
    _, state_store, _, _, _ = stores
    with pytest.raises(FileNotFoundError):
        state_store.load_run(new_id("run"))


def test_save_updates_state_and_stamps_updated_at(stores):
    _, state_store, _, _, _ = stores
    run_id = new_id("run")
    state = _state(run_id)
    state_store.create_run(state)
    before = state.updated_at
    state.workflow_status = "APPROVED"
    state.policy_outcome = "APPROVE"
    state_store.save_run(state)
    loaded = state_store.load_run(run_id)
    assert (loaded.workflow_status, loaded.policy_outcome) == ("APPROVED", "APPROVE")
    assert loaded.updated_at >= before


def test_audit_sequence_must_be_contiguous(stores):
    _, _, audit_store, _, _ = stores
    run_id = new_id("run")
    audit_store.append(_event(run_id, 1))
    audit_store.append(_event(run_id, 2))
    with pytest.raises(PersistenceError):
        audit_store.append(_event(run_id, 4))
    with pytest.raises(PersistenceError):
        audit_store.append(_event(run_id, 2))
    assert audit_store.latest_sequence(run_id) == 2


def test_audit_rejects_duplicate_event_id_and_bad_schema(stores):
    _, _, audit_store, _, _ = stores
    run_id = new_id("run")
    first = _event(run_id, 1)
    audit_store.append(first)
    with pytest.raises(PersistenceError):
        audit_store.append(_event(run_id, 2, event_id=first.event_id))
    with pytest.raises(UnsupportedSchemaError):
        audit_store.append(_event(run_id, 2, schema_version="audit.v0"))


def test_audit_read_preserves_order_content_and_run_isolation(stores):
    _, _, audit_store, _, _ = stores
    run_a, run_b = new_id("run"), new_id("run")
    written = [_event(run_a, i) for i in (1, 2, 3)]
    for event in written:
        audit_store.append(event)
    audit_store.append(_event(run_b, 1))
    read = audit_store.read_events(run_a)
    assert [e.to_dict() for e in read] == [e.to_dict() for e in written]
    assert len(audit_store.read_events(run_b)) == 1
    assert audit_store.read_events(new_id("run")) == []


def test_foundation_run_through_injected_stores(stores, tmp_path: Path):
    backend, state_store, audit_store, evidence_store, engine = stores
    persistence = RunPersistence(
        tmp_path, state_store=state_store, audit_store=audit_store, evidence_store=evidence_store
    )
    foundation = AgentExecutionFoundation(artifacts_root=tmp_path, persistence=persistence)
    event = FailureEvent.from_dict(
        {
            "workflow": "ci",
            "job": "test",
            "failed_step": "pytest",
            "message": "AssertionError: expected True got False",
            "changed_paths": ["src/app.py"],
            "log_excerpt": "FAILED tests/test_app.py::test_login",
        }
    )
    result = foundation.run(event)
    assert result.status in {RunStatus.APPROVED, RunStatus.AWAITING_HUMAN}

    run_id = result.run.run_id
    events = audit_store.read_events(run_id)
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    assert events[0].event_type == "RUN_CREATED"
    state = state_store.load_run(run_id)
    assert state.last_event_sequence == len(events)
    assert state.workflow_status == result.workflow_status
    if engine is not None:
        mirrored = {record.ref for record in list_evidence(engine, run_id)}
        assert "input/failure-event.json" in mirrored
        assert any(ref.startswith("evaluations/") for ref in mirrored)
        assert backend in {"sqlite", "postgres"}

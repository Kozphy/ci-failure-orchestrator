"""HTTP contract of the /v1 API: validation, structured errors, idempotency, auth, readiness."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from ci_failure_orchestrator.server.app import create_app  # noqa: E402
from ci_failure_orchestrator.server.db import create_engine_from_url  # noqa: E402
from ci_failure_orchestrator.server.logs import JsonFormatter, log_event  # noqa: E402
from ci_failure_orchestrator.server.settings import ServerSettings  # noqa: E402
from ci_failure_orchestrator.server.worker import Worker  # noqa: E402

FAILURE = {
    "workflow": "ci",
    "job": "test",
    "failed_step": "pytest",
    "message": "AssertionError: expected True got False",
    "changed_paths": ["src/app.py"],
    "log_excerpt": "FAILED tests/test_app.py::test_login",
}


def _settings(tmp_path: Path, **overrides) -> ServerSettings:
    values = dict(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        artifacts_root=tmp_path / "artifacts",
        worker_id="worker-test",
        lease_seconds=60,
    )
    values.update(overrides)
    return ServerSettings(**values)


@pytest.fixture
def settings(tmp_path: Path) -> ServerSettings:
    return _settings(tmp_path)


@pytest.fixture
def client(settings: ServerSettings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _unreachable_db_settings(tmp_path: Path) -> ServerSettings:
    # A directory cannot be opened as a SQLite database file, so every query fails.
    db_dir = tmp_path / "is-a-directory"
    db_dir.mkdir()
    return _settings(tmp_path, database_url=f"sqlite:///{db_dir}")


def test_health_is_dependency_free(tmp_path: Path):
    broken = _unreachable_db_settings(tmp_path)
    with TestClient(create_app(broken, engine=create_engine_from_url(broken.database_url))) as test_client:
        response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_reports_ok(client: TestClient):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "artifacts": "ok"}}


def test_ready_returns_503_when_database_is_unreachable(tmp_path: Path):
    settings = _unreachable_db_settings(tmp_path)
    with TestClient(create_app(settings)) as test_client:
        ready = test_client.get("/ready")
        submit = test_client.post("/v1/runs", json={"failure": FAILURE})
    assert ready.status_code == 503
    assert ready.json()["status"] == "not_ready"
    assert ready.json()["checks"]["database"].startswith("unavailable:")
    assert submit.status_code == 503
    assert submit.json()["error"]["code"] == "storage_unavailable"
    assert "is-a-directory" not in submit.text


def test_submit_returns_202_with_location_and_request_id(client: TestClient):
    response = client.post("/v1/runs", json={"failure": FAILURE}, headers={"X-Request-ID": "req-123"})
    assert response.status_code == 202
    body = response.json()
    assert body["job_status"] == "QUEUED"
    assert body["created"] is True
    assert response.headers["Location"] == f"/v1/runs/{body['run_id']}"
    assert response.headers["X-Request-ID"] == "req-123"

    view = client.get(body["links"]["run"]).json()
    assert view["job_status"] == "QUEUED"
    assert view["workflow"] == "ci"


def test_invalid_request_id_is_replaced(client: TestClient):
    response = client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert response.headers["X-Request-ID"] != "bad id with spaces"
    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.parametrize(
    "failure, field",
    [
        ({**FAILURE, "unexpected": "x"}, "unexpected"),
        ({**FAILURE, "changed_paths": ["../etc/passwd"]}, "changed_paths"),
        ({**FAILURE, "changed_paths": ["/abs/path.py"]}, "changed_paths"),
        ({**FAILURE, "changed_paths": ["C:/Windows/x.py"]}, "changed_paths"),
        ({**FAILURE, "message": ""}, "message"),
        ({**FAILURE, "commit_sha": "not-a-sha"}, "commit_sha"),
        ({**FAILURE, "log_excerpt": "x" * 100_001}, "log_excerpt"),
    ],
)
def test_validation_errors_are_structured_and_do_not_echo_input(client: TestClient, failure, field):
    response = client.post("/v1/runs", json={"failure": failure})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"]
    assert any(field in [str(part) for part in detail["loc"]] for detail in error["details"])
    assert all(set(detail) == {"loc", "msg", "type"} for detail in error["details"])


def test_validation_error_does_not_echo_secret_values(client: TestClient):
    secret = "ghp_" + "A" * 36
    response = client.post("/v1/runs", json={"failure": {**FAILURE, "commit_sha": secret}})
    assert response.status_code == 422
    assert secret not in response.text


def test_idempotency_key_replay_and_conflict(client: TestClient):
    headers = {"Idempotency-Key": "ci-run-42-attempt-1"}
    first = client.post("/v1/runs", json={"failure": FAILURE}, headers=headers)
    replay = client.post("/v1/runs", json={"failure": FAILURE}, headers=headers)
    conflict = client.post("/v1/runs", json={"failure": {**FAILURE, "job": "lint"}}, headers=headers)
    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json()["run_id"] == first.json()["run_id"]
    assert replay.json()["created"] is False
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"


def test_same_body_with_new_key_or_no_key_creates_new_runs(client: TestClient):
    first = client.post("/v1/runs", json={"failure": FAILURE}, headers={"Idempotency-Key": "key-a"})
    second = client.post("/v1/runs", json={"failure": FAILURE}, headers={"Idempotency-Key": "key-b"})
    unkeyed = client.post("/v1/runs", json={"failure": FAILURE})
    assert [r.status_code for r in (first, second, unkeyed)] == [202, 202, 202]
    assert len({r.json()["run_id"] for r in (first, second, unkeyed)}) == 3


def test_json_logs_keep_reserved_field_names_and_redact_secrets():
    captured: list[logging.LogRecord] = []
    logger = logging.getLogger("cfo-test-logs")
    handler = logging.Handler()
    handler.emit = captured.append
    logger.addHandler(handler)
    try:
        log_event(logger, "probe", created=True, detail="token ghp_" + "B" * 36)
    finally:
        logger.removeHandler(handler)
    line = json.loads(JsonFormatter().format(captured[0]))
    assert line["created_"] is True
    assert "ghp_" + "B" * 36 not in line["detail"]


def test_unknown_run_is_structured_404(client: TestClient):
    response = client.get("/v1/runs/run-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert client.get("/v1/runs/run-000000000000/events").status_code == 404


def test_unknown_route_uses_error_envelope(client: TestClient):
    response = client.get("/v2/nothing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_oversized_body_is_rejected_before_parsing(tmp_path: Path):
    settings = _settings(tmp_path, max_body_bytes=2048)
    with TestClient(create_app(settings)) as test_client:
        response = test_client.post("/v1/runs", json={"failure": {**FAILURE, "log_excerpt": "x" * 5000}})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_bearer_token_required_when_configured(tmp_path: Path):
    settings = _settings(tmp_path, api_token="test-token-not-a-secret")
    with TestClient(create_app(settings)) as test_client:
        missing = test_client.post("/v1/runs", json={"failure": FAILURE})
        wrong = test_client.get("/v1/runs", headers={"Authorization": "Bearer nope"})
        ok = test_client.get("/v1/runs", headers={"Authorization": "Bearer test-token-not-a-secret"})
        health = test_client.get("/health")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert ok.status_code == 200
    assert health.status_code == 200
    assert "test-token-not-a-secret" not in repr(settings)


def test_openapi_documents_versioned_routes(client: TestClient):
    spec = client.get("/openapi.json").json()
    for path in ("/health", "/ready", "/v1/runs", "/v1/runs/{run_id}", "/v1/runs/{run_id}/events"):
        assert path in spec["paths"]
    assert "ErrorResponse" in spec["components"]["schemas"]


def test_end_to_end_submit_process_and_read(client: TestClient, settings: ServerSettings):
    accepted = client.post("/v1/runs", json={"failure": FAILURE}).json()
    worker = Worker(client.app.state.engine, settings)
    assert worker.tick().value == "PROCESSED"

    view = client.get(f"/v1/runs/{accepted['run_id']}").json()
    assert view["job_status"] == "COMPLETED"
    assert view["workflow_status"] in {"APPROVED", "AWAITING_HUMAN"}
    assert view["failure_class"] == "test_failure"
    assert view["claim_count"] == 1

    events = client.get(f"/v1/runs/{accepted['run_id']}/events").json()
    assert events["count"] > 5
    assert [e["sequence"] for e in events["items"]] == list(range(1, events["count"] + 1))

    evidence = client.get(f"/v1/runs/{accepted['run_id']}/evidence").json()
    refs = {item["ref"] for item in evidence["items"]}
    assert "input/failure-event.json" in refs
    assert all(len(item["sha256"]) == 64 for item in evidence["items"])

    listed = client.get("/v1/runs", params={"status": "COMPLETED"}).json()
    assert accepted["run_id"] in {item["run_id"] for item in listed["items"]}

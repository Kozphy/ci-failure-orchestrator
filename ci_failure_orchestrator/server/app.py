"""FastAPI application: health, readiness and the versioned ``/v1/runs`` API.

The API only validates, enqueues and reads. Runs execute in ``server.worker`` so a slow or
crashing run never blocks or takes down request handling. Start with::

    uvicorn ci_failure_orchestrator.server.app:create_app --factory --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import hmac
import logging
import os
import re
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__ as _package_version
from ..foundation.durable import DurableRunState, PersistenceError
from .db import check_database, create_engine_from_url, init_db
from .jobs import IdempotencyConflictError, JobQueue, JobRecord, JobStatus
from .logs import configure_logging, log_event
from .schemas import (
    API_VERSION,
    AuditEventList,
    AuditEventOut,
    CreateRunRequest,
    ErrorDetail,
    ErrorResponse,
    EvidenceList,
    EvidenceOut,
    HealthResponse,
    ReadyResponse,
    RunAccepted,
    RunLinks,
    RunList,
    RunView,
)
from .settings import ServerSettings
from .sql_store import SqlAuditStore, SqlStateStore, list_evidence

logger = logging.getLogger("ci_failure_orchestrator.server.api")

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HTTP_CODES = {401: "unauthorized", 404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}
RunId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]


def _service_version() -> str:
    try:
        return version("ci-failure-orchestrator")
    except PackageNotFoundError:
        return _package_version


class ApiError(Exception):
    """Error rendered as an ``ErrorResponse`` with a stable machine-readable code."""

    def __init__(self, status_code: int, code: str, message: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, request_id=_request_id(request), details=details)
    )
    response = JSONResponse(status_code=status_code, content=body.model_dump(mode="json"), headers=headers)
    if _request_id(request):
        response.headers["X-Request-ID"] = _request_id(request) or ""
    return response


def _links(run_id: str) -> RunLinks:
    base = f"/{API_VERSION}/runs/{run_id}"
    return RunLinks(run=base, events=f"{base}/events", evidence=f"{base}/evidence")


def _run_view(job: JobRecord, state: DurableRunState | None) -> RunView:
    return RunView(
        run_id=job.run_id,
        job_id=job.job_id,
        job_status=job.status.value,
        workflow=job.workflow,
        repository=job.repository,
        workflow_status=state.workflow_status if state else job.workflow_status,
        technical_status=state.technical_status if state else None,
        policy_outcome=state.policy_outcome if state else None,
        current_attempt=state.current_attempt if state else 0,
        failure_class=job.failure_class,
        stop_reason=state.stop_reason if state else None,
        error=job.error,
        claim_count=job.claim_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        links=_links(job.run_id),
    )


def create_app(settings: ServerSettings | None = None, *, engine: Engine | None = None) -> FastAPI:
    """Build the FastAPI app.

    Args:
        settings: Server settings; read from ``CFO_*`` environment variables when omitted.
        engine: SQLAlchemy engine to use instead of one built from ``settings.database_url``.

    Returns:
        The configured application.
    """
    settings = settings or ServerSettings.from_env()
    owns_engine = engine is None
    engine = engine or create_engine_from_url(settings.database_url)
    queue = JobQueue(engine)
    state_store = SqlStateStore(engine)
    audit_store = SqlAuditStore(engine)

    def ensure_schema() -> None:
        if not app.state.schema_ready:
            init_db(engine)
            app.state.schema_ready = True

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        try:
            ensure_schema()
        except SQLAlchemyError as exc:
            log_event(logger, "schema_init_deferred", level=logging.WARNING, error_type=type(exc).__name__)
        yield
        if owns_engine:
            engine.dispose()

    app = FastAPI(
        title="CI Failure Orchestrator API",
        version=_service_version(),
        description=(
            "Submit CI failures to the agent execution foundation and read durable run state, "
            "audit events and evidence. Runs execute asynchronously in the worker."
        ),
        lifespan=lifespan,
        responses={
            401: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.schema_ready = False

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        request.state.request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        started = time.perf_counter()
        length = request.headers.get("Content-Length")
        if length is not None and (not length.isdigit() or int(length) > settings.max_body_bytes):
            response: Response = _error(
                request, 413, "payload_too_large", f"request body exceeds {settings.max_body_bytes} bytes"
            )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        log_event(
            logger,
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            request_id=request.state.request_id,
        )
        return response

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _error(request, exc.status_code, exc.code, exc.message, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(err.get("loc", ())), "msg": str(err.get("msg", "")), "type": str(err.get("type", ""))}
            for err in exc.errors()
        ]
        return _error(request, 422, "validation_error", "request validation failed", details=details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return _error(request, exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None))

    @app.exception_handler(SQLAlchemyError)
    @app.exception_handler(PersistenceError)
    async def _storage_error(request: Request, exc: Exception) -> JSONResponse:
        log_event(
            logger,
            "storage_unavailable",
            level=logging.ERROR,
            error_type=type(exc).__name__,
            request_id=_request_id(request),
        )
        return _error(request, 503, "storage_unavailable", "storage backend unavailable; retry later")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log_event(
            logger, "unhandled_error", level=logging.ERROR, error_type=type(exc).__name__, request_id=_request_id(request)
        )
        return _error(request, 500, "internal_error", "internal server error")

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if not settings.api_token:
            return
        scheme, _, supplied = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode(), settings.api_token.encode()):
            raise ApiError(401, "unauthorized", "missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    def find_job(run_id: str) -> JobRecord:
        ensure_schema()
        job = queue.get_by_run(run_id)
        if job is None:
            raise ApiError(404, "not_found", f"run not found: {run_id}")
        return job

    def load_state(run_id: str) -> DurableRunState | None:
        try:
            return state_store.load_run(run_id)
        except FileNotFoundError:
            return None

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    def health() -> HealthResponse:
        """Liveness probe; never touches the database."""
        return HealthResponse(status="ok", version=_service_version())

    @app.get(
        "/ready",
        response_model=ReadyResponse,
        tags=["operations"],
        responses={503: {"model": ReadyResponse}},
    )
    def ready() -> JSONResponse:
        """Readiness probe: database reachable with schema, artifacts root writable."""
        checks: dict[str, str] = {}
        try:
            ensure_schema()
            check_database(engine)
            checks["database"] = "ok"
        except SQLAlchemyError as exc:
            checks["database"] = f"unavailable: {type(exc).__name__}"
        try:
            settings.artifacts_root.mkdir(parents=True, exist_ok=True)
            fd, probe = tempfile.mkstemp(prefix=".ready-", dir=settings.artifacts_root)
            os.close(fd)
            os.unlink(probe)
            checks["artifacts"] = "ok"
        except OSError as exc:
            checks["artifacts"] = f"not writable: {type(exc).__name__}"
        ok = all(value == "ok" for value in checks.values())
        body = ReadyResponse(status="ready" if ok else "not_ready", checks=checks)
        return JSONResponse(status_code=200 if ok else 503, content=body.model_dump())

    @app.post(
        f"/{API_VERSION}/runs",
        response_model=RunAccepted,
        status_code=202,
        tags=["runs"],
        dependencies=[Depends(require_token)],
        responses={200: {"model": RunAccepted, "description": "Idempotent replay"}, 409: {"model": ErrorResponse}},
    )
    def create_run(
        body: CreateRunRequest,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=255, pattern=r"^[A-Za-z0-9._:-]{1,255}$")
        ] = None,
    ) -> RunAccepted:
        """Validate a CI failure and queue a foundation run for the worker."""
        ensure_schema()
        failure = body.failure
        try:
            result = queue.enqueue(
                failure.model_dump(),
                workflow=failure.workflow,
                repository=failure.repository,
                idempotency_key=idempotency_key,
            )
        except IdempotencyConflictError as exc:
            raise ApiError(409, "idempotency_conflict", str(exc)) from exc
        job = result.job
        response.status_code = 202 if result.created else 200
        response.headers["Location"] = _links(job.run_id).run
        log_event(logger, "run_enqueued", run_id=job.run_id, job_id=job.job_id, job_created=result.created)
        return RunAccepted(
            run_id=job.run_id,
            job_id=job.job_id,
            job_status=job.status.value,
            created=result.created,
            links=_links(job.run_id),
        )

    @app.get(f"/{API_VERSION}/runs", response_model=RunList, tags=["runs"], dependencies=[Depends(require_token)])
    def list_runs(
        status: JobStatus | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> RunList:
        """List runs, newest first."""
        ensure_schema()
        items = [_run_view(job, load_state(job.run_id)) for job in queue.list_jobs(status=status, limit=limit)]
        return RunList(items=items, count=len(items))

    @app.get(
        f"/{API_VERSION}/runs/{{run_id}}",
        response_model=RunView,
        tags=["runs"],
        dependencies=[Depends(require_token)],
        responses={404: {"model": ErrorResponse}},
    )
    def get_run(run_id: RunId) -> RunView:
        """Return job status and durable workflow state for one run."""
        job = find_job(run_id)
        return _run_view(job, load_state(run_id))

    @app.get(
        f"/{API_VERSION}/runs/{{run_id}}/events",
        response_model=AuditEventList,
        tags=["runs"],
        dependencies=[Depends(require_token)],
        responses={404: {"model": ErrorResponse}},
    )
    def get_run_events(run_id: RunId) -> AuditEventList:
        """Return the run's audit events in sequence order."""
        find_job(run_id)
        items = [AuditEventOut.model_validate(event.to_dict()) for event in audit_store.read_events(run_id)]
        return AuditEventList(run_id=run_id, items=items, count=len(items))

    @app.get(
        f"/{API_VERSION}/runs/{{run_id}}/evidence",
        response_model=EvidenceList,
        tags=["runs"],
        dependencies=[Depends(require_token)],
        responses={404: {"model": ErrorResponse}},
    )
    def get_run_evidence(run_id: RunId) -> EvidenceList:
        """Return metadata and SHA-256 digests of the run's mirrored evidence."""
        find_job(run_id)
        items = [EvidenceOut(**record.__dict__) for record in list_evidence(engine, run_id)]
        return EvidenceList(run_id=run_id, items=items, count=len(items))

    return app

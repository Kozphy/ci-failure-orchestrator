"""Pydantic request and response models for the ``/v1`` API.

Request models reject unknown fields and bound every string and list so a single request
cannot exhaust memory or smuggle unexpected keys into the runner.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

API_VERSION = "v1"


class FailureEventIn(BaseModel):
    """CI failure submitted for repair; maps onto ``foundation.models.FailureEvent``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    workflow: str = Field(min_length=1, max_length=255, examples=["ci"])
    job: str = Field(min_length=1, max_length=255, examples=["test"])
    failed_step: str = Field(min_length=1, max_length=255, examples=["pytest"])
    message: str = Field(min_length=1, max_length=8_000, examples=["AssertionError: expected True got False"])
    repository: str = Field(default="", max_length=255, pattern=r"^$|^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    commit_sha: str = Field(default="", max_length=64, pattern=r"^$|^[0-9a-fA-F]{7,64}$")
    branch: str = Field(default="", max_length=255)
    exit_code: int | None = Field(default=None, ge=-255, le=255)
    changed_paths: list[str] = Field(default_factory=list, max_length=500)
    log_excerpt: str = Field(default="", max_length=100_000)
    source: str = Field(default="api", max_length=64)

    @field_validator("changed_paths")
    @classmethod
    def _relative_paths_only(cls, paths: list[str]) -> list[str]:
        for path in paths:
            if not path or len(path) > 1024:
                raise ValueError("changed path must be 1-1024 characters")
            normalized = path.replace("\\", "/")
            pure = PurePosixPath(normalized)
            if pure.is_absolute() or ".." in pure.parts or ":" in normalized.split("/")[0]:
                raise ValueError("changed paths must be relative and stay inside the repository")
        return paths


class CreateRunRequest(BaseModel):
    """Body of ``POST /v1/runs``; same shape as the ``foundation-run`` fixture files."""

    model_config = ConfigDict(extra="forbid")

    failure: FailureEventIn


class RunLinks(BaseModel):
    """Related resource URLs."""

    run: str
    events: str
    evidence: str


class RunAccepted(BaseModel):
    """Response of ``POST /v1/runs``."""

    run_id: str
    job_id: str
    job_status: str
    created: bool = Field(description="False when an Idempotency-Key replay returned an existing run")
    links: RunLinks


class RunView(BaseModel):
    """Current status of a run: job processing state plus the governed workflow outcome."""

    run_id: str
    job_id: str
    job_status: str
    workflow: str
    repository: str
    workflow_status: str | None = None
    technical_status: str | None = None
    policy_outcome: str | None = None
    current_attempt: int = 0
    failure_class: str | None = None
    stop_reason: str | None = None
    error: str | None = None
    claim_count: int = 0
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    links: RunLinks


class RunList(BaseModel):
    """Response of ``GET /v1/runs``."""

    items: list[RunView]
    count: int


class EvidenceRefOut(BaseModel):
    """Evidence reference attached to an audit event."""

    kind: str
    ref: str
    content_type: str


class AuditEventOut(BaseModel):
    """One audit event."""

    sequence: int
    event_id: str
    event_type: str
    timestamp: str
    actor: str
    component: str
    state_before: str | None = None
    state_after: str | None = None
    evidence_refs: list[EvidenceRefOut] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditEventList(BaseModel):
    """Response of ``GET /v1/runs/{run_id}/events``."""

    run_id: str
    items: list[AuditEventOut]
    count: int


class EvidenceOut(BaseModel):
    """Metadata of one mirrored evidence document."""

    kind: str
    ref: str
    content_type: str
    sha256: str
    size_bytes: int
    written_at: str


class EvidenceList(BaseModel):
    """Response of ``GET /v1/runs/{run_id}/evidence``."""

    run_id: str
    items: list[EvidenceOut]
    count: int


class HealthResponse(BaseModel):
    """Liveness: the process is up. Does not touch dependencies."""

    status: Literal["ok"]
    version: str


class ReadyResponse(BaseModel):
    """Readiness: dependencies needed to serve traffic are reachable."""

    status: Literal["ready", "not_ready"]
    checks: dict[str, str]


class ErrorDetail(BaseModel):
    """Machine-readable error payload."""

    code: str
    message: str
    request_id: str | None = None
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    """Envelope for every non-2xx response."""

    error: ErrorDetail

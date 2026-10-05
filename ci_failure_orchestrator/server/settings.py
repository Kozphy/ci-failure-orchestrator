"""Server configuration read from environment variables.

Secrets (database password, API token) are only ever read from the environment and are
never included in ``repr`` or log output.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DEFAULT_DATABASE_URL = "sqlite:///./artifacts/orchestrator.db"


def redact_database_url(url: str) -> str:
    """Return the URL with any password replaced by ``***``."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    netloc = f"{parts.username}:***@{host}" if parts.username else f"***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _int_env(env: dict[str, str], name: str, default: int, minimum: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _float_env(env: dict[str, str], name: str, default: float, minimum: float) -> float:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


@dataclass(frozen=True)
class ServerSettings:
    """Runtime settings shared by the API process and the worker.

    Attributes:
        database_url: SQLAlchemy URL (``postgresql+psycopg://...`` or ``sqlite:///...``).
        artifacts_root: Directory for evidence files; must be shared by API and worker.
        api_token: Optional shared bearer token for ``/v1`` routes. Not RBAC.
        max_body_bytes: Requests with a larger ``Content-Length`` are rejected with 413.
        lease_seconds: How long a worker owns a claimed job without renewing its lease.
        poll_seconds: Worker sleep between empty polls.
        worker_id: Identifier recorded as the lease owner and audit actor.
    """

    database_url: str = DEFAULT_DATABASE_URL
    artifacts_root: Path = Path("artifacts")
    api_token: str | None = field(default=None, repr=False)
    max_body_bytes: int = 1_048_576
    lease_seconds: int = 300
    poll_seconds: float = 2.0
    worker_id: str = "worker-local"

    def __repr__(self) -> str:
        """Return a representation with the database password and API token redacted."""
        return (
            f"ServerSettings(database_url={redact_database_url(self.database_url)!r}, "
            f"artifacts_root={str(self.artifacts_root)!r}, api_token={'***' if self.api_token else None}, "
            f"max_body_bytes={self.max_body_bytes}, lease_seconds={self.lease_seconds}, "
            f"poll_seconds={self.poll_seconds}, worker_id={self.worker_id!r})"
        )

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ServerSettings:
        """Build settings from ``CFO_*`` environment variables.

        Args:
            env: Mapping to read instead of ``os.environ`` (used by tests).

        Returns:
            The parsed settings.

        Raises:
            ValueError: If a numeric variable is malformed or out of range.
        """
        source = dict(os.environ if env is None else env)
        token = (source.get("CFO_API_TOKEN") or "").strip() or None
        return cls(
            database_url=source.get("CFO_DATABASE_URL") or DEFAULT_DATABASE_URL,
            artifacts_root=Path(source.get("CFO_ARTIFACTS_ROOT") or "artifacts"),
            api_token=token,
            max_body_bytes=_int_env(source, "CFO_MAX_BODY_BYTES", 1_048_576, 1024),
            lease_seconds=_int_env(source, "CFO_LEASE_SECONDS", 300, 5),
            poll_seconds=_float_env(source, "CFO_POLL_SECONDS", 2.0, 0.05),
            worker_id=source.get("CFO_WORKER_ID") or f"worker-{os.getpid()}",
        )

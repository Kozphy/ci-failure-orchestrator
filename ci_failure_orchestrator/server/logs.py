"""Structured JSON logging for the API and worker.

Every string field passes through the foundation secret redactor before it is emitted.
Request and response bodies and headers are never logged.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..foundation.sanitization import sanitize_text

_RESERVED = set(vars(logging.makeLogRecord({})))


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)[0][:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _clean(str(value))


class JsonFormatter(logging.Formatter):
    """Format records as one JSON object per line with redacted string fields."""

    def format(self, record: logging.LogRecord) -> str:
        """Return the record as a JSON line."""
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": _clean(record.getMessage()),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = _clean(value)
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_type"] = record.exc_info[0].__name__
        return json.dumps(payload, sort_keys=True)


def configure_logging(level: str = "INFO") -> None:
    """Add a stderr ``JsonFormatter`` handler to the root logger (idempotent; keeps other handlers)."""
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Log ``event`` with extra structured fields.

    Field names that collide with ``LogRecord`` attributes (``created``, ``name``, ...) are
    emitted with a trailing underscore instead of being dropped.
    """
    logger.log(level, event, extra={(f"{k}_" if k in _RESERVED else k): v for k, v in fields.items()})

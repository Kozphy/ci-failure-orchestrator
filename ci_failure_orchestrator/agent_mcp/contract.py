"""Input and output checks for the one read-only diagnosis tool.

Validation uses the standard library. A failing check raises ToolError and does not call the doctor.
"""

from __future__ import annotations

from typing import Any

from ..doctor.diagnose import SCHEMA as DIAGNOSIS_SCHEMA

TOOL_NAME = "diagnose_saved_log"
MAX_TEXT_CHARS = 200_000
MAX_NAME_CHARS = 255
_ALLOWED_ARGUMENTS = frozenset({"log_text", "job", "step"})


class ToolError(Exception):
    """Stable error code plus a message safe to return to a client."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_arguments(arguments: Any) -> dict[str, str]:
    """Return job and step defaults after rejecting unknown or oversized fields."""
    if not isinstance(arguments, dict):
        raise ToolError("invalid_input", "arguments must be an object")
    extra = sorted(set(arguments) - _ALLOWED_ARGUMENTS)
    if extra:
        raise ToolError("invalid_input", "unknown arguments: " + ", ".join(extra))
    log_text = arguments.get("log_text")
    if not isinstance(log_text, str):
        raise ToolError("invalid_input", "log_text must be a string")
    if len(log_text) > MAX_TEXT_CHARS:
        raise ToolError("too_large", f"log_text exceeds {MAX_TEXT_CHARS} characters")
    job = arguments.get("job", "job")
    step = arguments.get("step", "")
    if not isinstance(job, str) or not isinstance(step, str):
        raise ToolError("invalid_input", "job and step must be strings")
    if len(job) > MAX_NAME_CHARS or len(step) > MAX_NAME_CHARS:
        raise ToolError("invalid_input", f"job and step must be at most {MAX_NAME_CHARS} characters")
    return {"log_text": log_text, "job": job or "job", "step": step}


def validate_result(payload: Any) -> dict[str, Any]:
    """Confirm the wrapper the server is about to return. Does not re-grade the log."""
    if not isinstance(payload, dict):
        raise ToolError("internal_error", "tool result was not an object")
    diagnosis = payload.get("diagnosis")
    if payload.get("ok") is not True or payload.get("untrusted") is not True:
        raise ToolError("internal_error", "tool result missed ok or untrusted")
    if payload.get("tool") != TOOL_NAME:
        raise ToolError("internal_error", "tool result named the wrong tool")
    if not isinstance(payload.get("notice"), str) or not payload["notice"]:
        raise ToolError("internal_error", "tool result missed the untrusted notice")
    if not isinstance(diagnosis, dict) or diagnosis.get("schema") != DIAGNOSIS_SCHEMA:
        raise ToolError("internal_error", "diagnosis schema was not actions-doctor.diagnosis.v1")
    return payload

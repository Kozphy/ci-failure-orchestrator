"""One read-only tool: diagnose a saved CI log with the existing CI Doctor."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..doctor.diagnose import diagnose_log
from ..foundation.sanitization import sanitize_text
from ..server.logs import log_event
from ..service.untrusted import UNTRUSTED_NOTICE, clean_untrusted
from .contract import TOOL_NAME, validate_arguments, validate_result

logger = logging.getLogger("ci_failure_orchestrator.agent_mcp")
MAX_FIELD_CHARS = 8_000
DENIED_TOOLS = frozenset({"apply", "merge", "fix-repo-apply", "shell", "exec", "push", "delete"})

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["log_text"],
    "properties": {
        "log_text": {"type": "string", "maxLength": 200000},
        "job": {"type": "string", "maxLength": 255},
        "step": {"type": "string", "maxLength": 255},
    },
}


def _clip(text: str) -> str:
    cleaned = clean_untrusted(text)
    if len(cleaned) > MAX_FIELD_CHARS:
        return cleaned[:MAX_FIELD_CHARS] + "…[truncated]"
    return cleaned


def redact_value(value: Any) -> Any:
    """Neutralize workflow commands and redact secrets in every returned string."""
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, dict):
        return {str(key): redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _clip(str(value))


def diagnose_saved_log(arguments: Any) -> dict[str, Any]:
    """Diagnose one saved log. No network, no shell, no write to the repository."""
    fields = validate_arguments(arguments)
    diagnosis = diagnose_log(fields["log_text"], job=fields["job"], step=fields["step"])
    payload = {
        "ok": True,
        "untrusted": True,
        "tool": TOOL_NAME,
        "notice": UNTRUSTED_NOTICE,
        "evidence_class": "saved_log",
        "log_excerpt": _clip(fields["log_text"][:4000]),
        "diagnosis": redact_value(diagnosis.to_dict()),
    }
    return validate_result(payload)


def append_audit(path: Path | None, record: dict[str, Any]) -> None:
    """Append one redacted activation record. The CI log is never included."""
    safe = {key: sanitize_text(value)[0] if isinstance(value, str) else value for key, value in record.items()}
    log_event(logger, str(safe.get("event") or "mcp_audit"), **{k: v for k, v in safe.items() if k != "event"})
    if path is None:
        return
    line = json.dumps(safe, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")

"""Read-only agent tools over existing diagnosis, audit, and evidence functions.

These functions do not call GitHub, do not run shell commands, and do not merge.
Log and report text is untrusted data: it is neutralized and secret-redacted before return.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..ci_audit import EXPORT_SCHEMA, analyze_export, render_report
from ..doctor.diagnose import diagnose_log
from ..foundation.sanitization import sanitize_text
from ..service.evidence_report import build_repair_evidence
from ..service.untrusted import UNTRUSTED_NOTICE, clean_untrusted

MAX_TEXT_CHARS = 200_000
MAX_FILE_BYTES = 2_000_000
MAX_FIELD_CHARS = 8_000
_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

DENIED_TOOLS = frozenset(
    {
        "apply",
        "merge",
        "fix-repo-apply",
        "shell",
        "exec",
        "push",
        "delete",
    }
)


class ToolError(Exception):
    """Structured tool failure. ``code`` is stable; ``message`` is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _clip(text: str) -> str:
    cleaned = clean_untrusted(text)
    if len(cleaned) > MAX_FIELD_CHARS:
        return cleaned[:MAX_FIELD_CHARS] + "…[truncated]"
    return cleaned


def redact_value(value: Any) -> Any:
    """Redact secrets and neutralize workflow commands in every string."""
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, dict):
        return {str(k): redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _clip(str(value))


def resolve_under_root(root: Path, relative: str) -> Path:
    """Resolve ``relative`` inside ``root``. Reject absolute paths and ``..``."""
    if not isinstance(relative, str) or not relative.strip():
        raise ToolError("invalid_input", "path must be a non-empty relative path")
    raw = relative.replace("\\", "/").strip()
    if raw.startswith("/") or ":" in raw.split("/", 1)[0]:
        raise ToolError("invalid_input", "absolute paths are not allowed")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ToolError("invalid_input", "path traversal is not allowed")
    root_resolved = root.resolve()
    candidate = (root_resolved.joinpath(*parts)).resolve()
    if not candidate.is_relative_to(root_resolved):
        raise ToolError("invalid_input", "path escapes the allowed root")
    if not candidate.is_file():
        raise ToolError("not_found", "file does not exist under the allowed root")
    if candidate.stat().st_size > MAX_FILE_BYTES:
        raise ToolError("too_large", f"file exceeds {MAX_FILE_BYTES} bytes")
    return candidate


def diagnose_saved_log(*, log_text: str, job: str = "job", step: str = "") -> dict[str, Any]:
    """Diagnose one saved job log with the existing CI Doctor. No network."""
    if not isinstance(log_text, str):
        raise ToolError("invalid_input", "log_text must be a string")
    if len(log_text) > MAX_TEXT_CHARS:
        raise ToolError("too_large", f"log_text exceeds {MAX_TEXT_CHARS} characters")
    if not isinstance(job, str) or not isinstance(step, str):
        raise ToolError("invalid_input", "job and step must be strings")
    if len(job) > 255 or len(step) > 255:
        raise ToolError("invalid_input", "job and step must be at most 255 characters")
    diagnosis = diagnose_log(log_text, job=job or "job", step=step)
    return {
        "ok": True,
        "untrusted": True,
        "notice": UNTRUSTED_NOTICE,
        "log_excerpt": _clip(log_text[:4000]),
        "diagnosis": redact_value(diagnosis.to_dict()),
    }


def summarize_reliability_export(*, root: Path, export_path: str) -> dict[str, Any]:
    """Summarize a local ``ci-audit.export.v1`` file. Does not contact GitHub."""
    path = resolve_under_root(root, export_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ToolError("invalid_input", "export could not be read as text") from exc
    except json.JSONDecodeError as exc:
        raise ToolError("invalid_input", "export is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ToolError("invalid_input", "export must be a JSON object")
    try:
        analysis = analyze_export(payload)
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        raise ToolError("invalid_input", sanitize_text(str(exc))[0][:500] or "export could not be analyzed") from exc
    totals = analysis.get("totals") or {}
    findings = analysis.get("findings") or []
    report = render_report(analysis)
    return {
        "ok": True,
        "untrusted": True,
        "notice": UNTRUSTED_NOTICE,
        "schema": EXPORT_SCHEMA,
        "summary": redact_value(
            {
                "window_days": payload.get("window_days"),
                "failure_rate": totals.get("failure_rate"),
                "completed_runs": totals.get("completed"),
                "failed_runs": totals.get("failed"),
                "finding_count": len(findings),
                "finding_ids": [item.get("id") for item in findings if isinstance(item, dict)],
            }
        ),
        "report_markdown": _clip(report),
    }


def get_repair_evidence(*, root: Path, run_id: str) -> dict[str, Any]:
    """Read one stored repair evidence report. Does not re-run verification."""
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ToolError("invalid_input", "run_id must match [A-Za-z0-9_.-]{1,64}")
    run_dir = (root.resolve() / "runs" / run_id).resolve()
    if not run_dir.is_relative_to(root.resolve()) or not run_dir.is_dir():
        raise ToolError("not_found", "no stored run with that id under the allowed root")
    report = build_repair_evidence(root, run_id)
    return {
        "ok": True,
        "untrusted": True,
        "notice": UNTRUSTED_NOTICE,
        "report": redact_value(report),
    }

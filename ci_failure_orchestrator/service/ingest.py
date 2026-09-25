"""Failure sources: fixture, log file, GitHub Actions run, local reproduction."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..github_client import GitHubActionsClient
from ..patch_sandbox import VerificationStep
from .common import MAX_LOG_CHARS, tail
from .session import VerifyCommand

_GH_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?", re.MULTILINE)
_MESSAGE_RE = re.compile(r"(error|failed|failure|exception|assert|traceback)", re.IGNORECASE)
_SOURCE_PATH_RE = re.compile(
    r"[A-Za-z0-9_.\-/\\:]+\.(?:py|pyi|js|jsx|mjs|cjs|ts|tsx|go|rs|java|kt|rb|php|cs|c|cc|cpp|h|hpp|swift|scala)\b"
)


def summarize_failure_message(log: str) -> str:
    lines = [line.strip() for line in log.splitlines() if line.strip()]
    hits = [line for line in lines if _MESSAGE_RE.search(line)]
    chosen = hits[-1] if hits else (lines[-1] if lines else "")
    return chosen[:300]


def related_tracked_paths(text: str, tracked: Sequence[str], *, limit: int = 8) -> tuple[str, ...]:
    """Tracked repository files mentioned in a log (absolute or relative paths)."""

    tracked_set = set(tracked)
    found: dict[str, None] = {}
    for raw in _SOURCE_PATH_RE.findall(text)[:400]:
        candidate = raw.replace("\\", "/")
        while candidate.startswith("./"):
            candidate = candidate[2:]
        if candidate in tracked_set:
            found.setdefault(candidate, None)
        else:
            for path in tracked:
                if candidate.endswith("/" + path):
                    found.setdefault(path, None)
                    break
        if len(found) >= limit:
            break
    return tuple(found)


def failure_from_fixture(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return dict(raw.get("failure", raw))


def failure_from_log_file(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    log = tail(text, MAX_LOG_CHARS)
    return {
        "source": "log_file",
        "workflow": "ci",
        "job": "ci",
        "failed_step": "unknown",
        "message": summarize_failure_message(log),
        "log_excerpt": log,
    }


def failure_from_github(
    repository: str,
    run_id: int,
    *,
    token: str | None = None,
    api_url: str = "https://api.github.com",
    timeout: float = 30.0,
) -> dict[str, Any]:
    evidence = GitHubActionsClient(token=token, api_url=api_url, timeout=timeout).collect_run(
        repository, run_id, include_logs=True
    )
    failed_conclusions = {"failure", "timed_out", "cancelled", "action_required"}
    job = next((j for j in evidence.jobs if j.get("conclusion") in failed_conclusions), None)
    if job is None:
        raise ValueError(f"no failed job found in {repository} run {run_id}")
    step = next(
        (s for s in job.get("steps") or [] if s.get("conclusion") in failed_conclusions),
        None,
    )
    job_name = str(job.get("name") or job.get("id"))
    log = _GH_TIMESTAMP_RE.sub("", evidence.logs.get(job_name, ""))
    log = tail(log, MAX_LOG_CHARS)
    return {
        "source": "github_actions",
        "repository": repository,
        "workflow": str(job.get("workflow_name") or "ci"),
        "job": job_name,
        "failed_step": str((step or {}).get("name") or "unknown"),
        "message": summarize_failure_message(log) or f"{job_name} failed",
        "commit_sha": str(job.get("head_sha") or ""),
        "branch": str(job.get("head_branch") or ""),
        "log_excerpt": log,
        "raw_log_ref": str(job.get("html_url") or ""),
    }


def failure_from_reproduction(steps: Sequence[VerificationStep], commands: Sequence[VerifyCommand]) -> dict[str, Any]:
    failing = next((s for s in steps if not s.passed), steps[-1])
    display = next((c.display for c in commands if c.name == failing.name), failing.name)
    output = tail(f"{failing.stdout}\n{failing.stderr}".strip(), MAX_LOG_CHARS)
    return {
        "source": "local_reproduction",
        "workflow": "local",
        "job": "verify",
        "failed_step": display,
        "message": summarize_failure_message(output) or f"{display} exited {failing.returncode}",
        "exit_code": failing.returncode,
        "log_excerpt": output,
    }

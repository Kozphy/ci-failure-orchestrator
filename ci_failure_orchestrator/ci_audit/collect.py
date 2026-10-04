"""Collect a sanitized GitHub Actions export for one repository (read-only)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from ..classifier import classify_error
from ..foundation.classifier import FailureClassifier, classify_ci_step
from ..foundation.models import FailureEvent
from ..github_client import GitHubAPIError
from ..service.common import MAX_LOG_CHARS, tail
from ..service.ingest import summarize_failure_message
from ..service.untrusted import clean_untrusted

EXPORT_SCHEMA = "ci-audit.export.v1"
FAILED_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
_GH_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?", re.MULTILINE)
_MESSAGE_LIMIT = 300
_ERROR_MARK = "##[error]"
_WARNING_MARK = "##[warning]"
_SECURITY_TOOL_RE = re.compile(r"(?i)gitleaks|trufflehog|codeql|trivy|bandit|semgrep|snyk|grype|secret[- ]?scan")
_SECURITY_MESSAGE_RE = re.compile(r"(?i)leaks? (?:detected|found)|secrets? detected|vulnerabilit(?:y|ies) found")
_STEP_CATEGORY = {
    "lint": "lint_failure",
    "formatting": "lint_failure",
    "typing": "type_failure",
    "workflow_syntax": "configuration_failure",
    "unit_test_failure": "test_failure",
}
_ENVIRONMENT_CATEGORIES = frozenset({"dependency_failure", "network_failure", "infrastructure_failure"})
_ENVIRONMENT_CLASSES = frozenset({"DEPENDENCY_ERROR", "NETWORK_ERROR", "PACKAGE_ERROR", "DEPLOYMENT_ERROR"})
_GENERIC_ERROR_RE = re.compile(r"(?i)^process completed with exit code \d+\.?$")
# Tool output that states the error itself (pip, mypy, tsc, pytest's summary, ruff/flake8 rule codes),
# not a help URL or a tally such as "Found 1 error.".
_EXPLICIT_ERROR_RE = re.compile(
    r"^(?:ERROR|Error|error)(?::|\[| TS\d+)|^FAILED |: error: |^[A-Z]{1,4}\d{3,4} (?:\[\*\] )?\S|:\d+:\d+: [A-Z]{1,4}\d{3,4} "
)

_RUN_FIELDS = (
    "id",
    "workflow_id",
    "name",
    "path",
    "event",
    "head_branch",
    "head_sha",
    "status",
    "conclusion",
    "run_attempt",
    "created_at",
    "run_started_at",
    "updated_at",
    "html_url",
)


class ActionsReader(Protocol):
    def list_workflow_runs(self, repository: str, *, created_since: str, max_runs: int) -> list[dict]: ...

    def list_run_jobs(self, repository: str, run_id: int) -> list[dict]: ...

    def job_log(self, repository: str, job_id: int) -> str: ...


def runner_os(labels: list[str]) -> str:
    lowered = [str(label).lower() for label in labels]
    if "self-hosted" in lowered:
        return "self-hosted"
    if any(label.startswith("windows") for label in lowered):
        return "windows"
    if any(label.startswith("macos") for label in lowered):
        return "macos"
    return "linux"


def _text(value: Any) -> str:
    return clean_untrusted(str(value or ""))


def workflow_label(run: dict) -> str:
    """Stable workflow name; Dependabot's dynamic runs get a new name per update."""
    path = str(run.get("path") or "")
    if path.startswith("dynamic/"):
        return f"{path.rsplit('/', 1)[-1]} (dynamic)"
    return str(run.get("name") or path or run.get("workflow_id") or "")


def _run_record(run: dict) -> dict:
    record = {field: run.get(field) for field in _RUN_FIELDS}
    for field in ("name", "path", "head_branch"):
        record[field] = _text(record[field])
    record["workflow"] = _text(workflow_label(run))
    return record


def job_record(job: dict) -> dict:
    labels = [str(label) for label in job.get("labels") or []]
    failed_step = next(
        (str(step.get("name") or "") for step in job.get("steps") or [] if step.get("conclusion") in FAILED_CONCLUSIONS),
        "",
    )
    return {
        "id": job.get("id"),
        "run_id": job.get("run_id"),
        "run_attempt": job.get("run_attempt") or 1,
        "name": _text(job.get("name")),
        "conclusion": job.get("conclusion"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "runner_os": runner_os(labels),
        "failed_step": _text(failed_step),
        "html_url": job.get("html_url"),
    }


def log_lines(log: str) -> list[str]:
    """Log lines without GitHub's timestamp prefix; indices match the downloaded log's lines."""
    return _GH_TIMESTAMP_RE.sub("", log).splitlines()


def failing_section(log: str) -> str:
    """The failing step's output, from its ``##[group]Run`` header to the first ``##[error]`` block.

    Post-job cleanup (checkout teardown, git config) and the echoed step script are
    dropped; they would otherwise dominate the tail, the message and the category.
    """
    lines = log_lines(log)
    cleanup = next((i for i, line in enumerate(lines) if line.strip() == "Post job cleanup."), len(lines))
    lines = lines[:cleanup]
    first_error = next((i for i, line in enumerate(lines) if line.startswith(_ERROR_MARK)), None)
    if first_error is None:
        start = max((i for i, line in enumerate(lines) if line.startswith("##[group]Run ")), default=0)
        return _drop_script_echo(lines[start:])
    start = max((i for i in range(first_error) if lines[i].startswith("##[group]Run ")), default=0)
    end = first_error
    while end + 1 < len(lines) and lines[end + 1].startswith(_ERROR_MARK):
        end += 1
    return _drop_script_echo(lines[start : end + 1])


def _drop_script_echo(lines: list[str]) -> str:
    """Keep the ``Run`` header line but drop the echoed script and env block under it."""
    if not lines or not lines[0].startswith("##[group]Run "):
        return "\n".join(lines)
    close = next((i for i, line in enumerate(lines) if line.startswith("##[endgroup]")), None)
    return "\n".join([lines[0], *lines[close + 1 :]] if close is not None else lines)


def failure_message(section: str) -> str:
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    errors = [line[len(_ERROR_MARK):].strip() for line in lines if line.startswith(_ERROR_MARK)]
    specific = [error for error in errors if not _GENERIC_ERROR_RE.match(error)]
    if specific:
        return specific[0]
    if not errors:
        warnings = [line[len(_WARNING_MARK):].strip() for line in lines if line.startswith(_WARNING_MARK)]
        if warnings:
            return warnings[-1]
    body_lines = [line for line in lines if not line.startswith("##[")]
    explicit = next((line for line in body_lines if _EXPLICIT_ERROR_RE.search(line)), "")
    return explicit or summarize_failure_message("\n".join(body_lines)) or (errors[0] if errors else "")


def classify_failure(workflow: str, job: dict, log: str) -> dict:
    """Taxonomy entry for one failed job; the log is reduced to one scrubbed line."""

    section = failing_section(log)
    excerpt = tail(clean_untrusted(section), MAX_LOG_CHARS)
    message = failure_message(section) or f"{job['name']} failed"
    event = FailureEvent(
        event_id=f"job-{job['id']}",
        run_id=str(job["run_id"]),
        source="github_actions",
        workflow=workflow,
        job=job["name"],
        failed_step=job["failed_step"] or "unknown",
        message=message,
        log_excerpt=excerpt,
    )
    classification = FailureClassifier().classify(event)
    header = next((line for line in section.splitlines() if line.startswith("##[group]Run ")), "")
    # The step that ran names the tool; a job called "tests" can fail in its pip install step.
    step_text = f"{job['failed_step']} {header}".strip() or job["name"]
    category, confidence, basis = refine_category(classification.category, classification.confidence, message, step_text)
    return {
        "run_id": job["run_id"],
        "run_attempt": job["run_attempt"],
        "job_id": job["id"],
        "workflow": workflow,
        "job": job["name"],
        "failed_step": job["failed_step"],
        "message": clean_untrusted(message)[:_MESSAGE_LIMIT],
        "category": category,
        "confidence": confidence,
        "classified_by": basis,
        "policy_category": classification.category,
        "policy_confidence": classification.confidence,
        "log_available": bool(log),
        "html_url": job["html_url"],
    }


def refine_category(category: str, confidence: float, message: str, step_text: str) -> tuple[str, float, str]:
    """Report-only refinement of the foundation category; the policy gate never sees this.

    The foundation lets any environment pattern anywhere in the log win, so a lint step
    whose output quotes ``import DependencyX`` reads as a dependency failure. When the
    step that ran names a tool and the error line itself carries no environment signal,
    the tool wins. Secret and security scanners get their own audit category.
    """
    if _SECURITY_TOOL_RE.search(step_text) or _SECURITY_MESSAGE_RE.search(message):
        return "security_scan_failure", 0.8, "step"
    tool = _STEP_CATEGORY.get(classify_ci_step("", step_text, step_text, ""), "")
    if tool and category in _ENVIRONMENT_CATEGORIES and classify_error(message)[0] not in _ENVIRONMENT_CLASSES:
        return tool, 0.7, "step"
    return category, confidence, "classifier"


def collect_export(
    reader: ActionsReader,
    repository: str,
    *,
    days: int = 30,
    max_runs: int = 500,
    max_logs: int = 50,
    now: datetime | None = None,
) -> dict:
    """Read-only pull of runs, jobs (all attempts) and classified failures."""

    if days <= 0 or max_runs <= 0 or max_logs < 0:
        raise ValueError("days and max_runs must be positive and max_logs non-negative")
    collected_at = now or datetime.now(timezone.utc)
    since = (collected_at - timedelta(days=days)).date().isoformat()
    raw_runs = reader.list_workflow_runs(repository, created_since=since, max_runs=max_runs)

    runs = [_run_record(run) for run in raw_runs]
    workflow_by_run = {run["id"]: run["workflow"] for run in runs}
    private = next((bool((run.get("repository") or {}).get("private")) for run in raw_runs), None)

    jobs: list[dict] = []
    warnings: list[str] = []
    for run in runs:
        if run["status"] != "completed":
            continue
        try:
            jobs.extend(job_record(job) for job in reader.list_run_jobs(repository, int(run["id"])))
        except (GitHubAPIError, OSError) as exc:
            warnings.append(f"jobs unavailable for run {run['id']}: {clean_untrusted(str(exc))[:200]}")

    failed_jobs = sorted(
        (job for job in jobs if job["conclusion"] in FAILED_CONCLUSIONS),
        key=lambda job: str(job["completed_at"] or ""),
        reverse=True,
    )
    failures: list[dict] = []
    log_errors: list[str] = []
    for index, job in enumerate(failed_jobs):
        log = ""
        if index < max_logs:
            try:
                log = reader.job_log(repository, int(job["id"]))
            except (GitHubAPIError, OSError) as exc:
                log_errors.append(clean_untrusted(str(exc))[:200])
        failures.append(classify_failure(workflow_by_run.get(job["run_id"], ""), job, log))
    if log_errors:
        warnings.append(f"{len(log_errors)} failed-job logs could not be downloaded; first error: {log_errors[0]}")

    return {
        "schema": EXPORT_SCHEMA,
        "repository": repository,
        "private": private,
        "collected_at": collected_at.isoformat(timespec="seconds"),
        "since": since,
        "window_days": days,
        "limits": {"max_runs": max_runs, "max_logs": max_logs, "runs_truncated": len(raw_runs) >= max_runs},
        "runs": runs,
        "jobs": jobs,
        "failures": failures,
        "warnings": warnings,
    }

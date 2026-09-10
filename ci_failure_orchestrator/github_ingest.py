"""GitHub Actions data ingestion for CI failure analysis.

This module provides functions to convert normalized GitHub Actions job data into
pipeline stages and failures for CI failure analysis. It handles job dependencies,
failure conclusions, and error message classification.
"""

from __future__ import annotations
from .classifier import classify_error
from .models import Failure, Stage


def stages_from_jobs(jobs: list[dict]) -> list[Stage]:
    """Convert normalized GitHub Actions jobs into pipeline stages.

    This function converts GitHub Actions job data into Stage objects,
    handling job dependencies (which may be a string or list). The GitHub
    jobs REST response does not expose workflow-level `needs`, so a collector
    may enrich jobs from workflow YAML to include cross-workflow dependencies.

    Args:
        jobs: List of GitHub Actions job dictionaries.

    Returns:
        List of Stage objects with id, dependencies, and criticality.

    Input Assumptions:
        - Each job dictionary has a "name" field.
        - Job dependencies are in the "needs" field (string or list).
        - Criticality is in the "criticality" field (defaults to 0.5).

    Side Effects:
        - None (pure data transformation).

    Failure Modes:
        - Missing job fields may raise KeyError.
        - Invalid job names may cause downstream analysis issues.
    """
    stages: list[Stage] = []
    for job in jobs:
        needs = job.get("needs", ())
        if isinstance(needs, str):
            needs = (needs,)
        stages.append(Stage(job["name"], tuple(needs or ()), float(job.get("criticality", 0.5))))
    return stages


def failures_from_jobs(jobs: list[dict], logs: dict[str, str] | None = None) -> list[Failure]:
    """Extract failures from GitHub Actions jobs with classification.

    This function identifies failed jobs (conclusion is failure, timed_out, cancelled,
    or action_required), extracts error messages from logs or job data, classifies
    the error type, and creates Failure objects with metadata.

    Args:
        jobs: List of GitHub Actions job dictionaries.
        logs: Optional dictionary mapping job names to log content.

    Returns:
        List of Failure objects with error type, message, severity, confidence, and metadata.

    Classification Logic:
        - Jobs with conclusion "timed_out" are classified as FLAKY_TEST (unless pattern matches).
        - Other failed jobs are classified using the classifier function.
        - Error messages are sourced from logs first, then job failure_message, then a default.

    Side Effects:
        - None (pure data extraction and classification).

    Failure Modes:
        - Missing job fields may raise KeyError.
        - Invalid log data may cause classification errors.
    """
    logs = logs or {}
    failures: list[Failure] = []
    for job in jobs:
        if job.get("conclusion") not in {"failure", "timed_out", "cancelled", "action_required"}:
            continue
        name = job["name"]
        message = logs.get(name) or job.get("failure_message") or f"{name} {job.get('conclusion', 'failure')}"
        error_type, confidence = classify_error(message)
        if job.get("conclusion") == "timed_out" and error_type == "UNKNOWN":
            error_type, confidence = "FLAKY_TEST", 0.6
        failures.append(Failure(name, error_type, message, float(job.get("severity", 0.5)), confidence, {"job_id": job.get("id"), "conclusion": job.get("conclusion"), "html_url": job.get("html_url")}))
    return failures

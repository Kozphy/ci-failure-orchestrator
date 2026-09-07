from __future__ import annotations
from .classifier import classify_error
from .models import Failure, Stage


def stages_from_jobs(jobs: list[dict]) -> list[Stage]:
    """Convert normalized GitHub Actions jobs into pipeline stages.

    `needs` may be a string or list. The GitHub jobs REST response does not
    expose workflow `needs`, so a collector may enrich jobs from workflow YAML.
    """
    stages: list[Stage] = []
    for job in jobs:
        needs = job.get("needs", ())
        if isinstance(needs, str):
            needs = (needs,)
        stages.append(Stage(job["name"], tuple(needs or ()), float(job.get("criticality", 0.5))))
    return stages


def failures_from_jobs(jobs: list[dict], logs: dict[str, str] | None = None) -> list[Failure]:
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

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class GitHubAPIError(RuntimeError):
    """Raised when GitHub Actions evidence cannot be collected safely."""


class _DropAuthOnCrossHostRedirect(HTTPRedirectHandler):
    """Log downloads redirect to blob storage; the GitHub token must not follow."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


_OPENER = build_opener(_DropAuthOnCrossHostRedirect)


def _check_repository(repository: str) -> None:
    owner, _, name = repository.partition("/")
    if not owner or not name or "/" in name:
        raise ValueError("repository must use owner/name format")


@dataclass(frozen=True)
class WorkflowRunEvidence:
    """Normalized jobs and logs collected from one GitHub Actions run."""

    jobs: list[dict]
    logs: dict[str, str]


class GitHubActionsClient:
    """Minimal GitHub REST client for workflow-run evidence collection.

    Authentication uses a bearer token supplied explicitly or via GITHUB_TOKEN.
    Every request is read-only except ``rerun_workflow_run``, which an operator invokes
    explicitly to re-run CI for a candidate fix.
    """

    def __init__(self, token: str | None = None, api_url: str = "https://api.github.com", timeout: float = 30.0):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, *, accept: str = "application/vnd.github+json", method: str = "GET") -> bytes:
        headers = {
            "Accept": accept,
            "User-Agent": "ci-failure-orchestrator",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = b"" if method == "POST" else None
        request = Request(f"{self.api_url}{path}", headers=headers, method=method, data=data)
        try:
            with _OPENER.open(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubAPIError(f"GitHub API returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise GitHubAPIError(f"Unable to reach GitHub API: {exc.reason}") from exc

    def _get_json(self, path: str) -> dict:
        try:
            return json.loads(self._request(path).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubAPIError("GitHub API returned invalid JSON") from exc

    def list_workflow_runs(self, repository: str, *, created_since: str, max_runs: int) -> list[dict]:
        """Newest-first workflow runs created on or after ``created_since`` (YYYY-MM-DD)."""
        _check_repository(repository)
        runs: list[dict] = []
        page = 1
        while len(runs) < max_runs:
            payload = self._get_json(
                f"/repos/{repository}/actions/runs?created=%3E%3D{created_since}&per_page=100&page={page}"
            )
            batch = payload.get("workflow_runs", [])
            if not isinstance(batch, list):
                raise GitHubAPIError("GitHub runs response did not contain a workflow_runs list")
            runs.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return runs[:max_runs]

    def get_run(self, repository: str, run_id: int) -> dict:
        """Return one workflow run's JSON object."""
        _check_repository(repository)
        return self._get_json(f"/repos/{repository}/actions/runs/{run_id}")

    def list_runs_for_commit(self, repository: str, head_sha: str) -> list[dict]:
        """Return workflow runs for one commit SHA (a single page of at most 100 runs)."""
        _check_repository(repository)
        payload = self._get_json(f"/repos/{repository}/actions/runs?head_sha={head_sha}&per_page=100")
        runs = payload.get("workflow_runs", [])
        if not isinstance(runs, list):
            raise GitHubAPIError("GitHub runs response did not contain a workflow_runs list")
        return runs

    def list_latest_jobs(self, repository: str, run_id: int) -> list[dict]:
        """Return jobs from a run's latest attempt (``filter=latest``, a single page of at most 100 jobs)."""
        _check_repository(repository)
        payload = self._get_json(f"/repos/{repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100")
        jobs = payload.get("jobs", [])
        if not isinstance(jobs, list):
            raise GitHubAPIError("GitHub jobs response did not contain a jobs list")
        return jobs

    def rerun_workflow_run(self, repository: str, run_id: int) -> None:
        """Request a re-run of a workflow run; this client's only write request."""
        _check_repository(repository)
        self._request(f"/repos/{repository}/actions/runs/{run_id}/rerun", method="POST")

    def list_run_jobs(self, repository: str, run_id: int) -> list[dict]:
        """Jobs from every attempt of a run (``filter=all``), so reruns stay visible."""
        _check_repository(repository)
        jobs: list[dict] = []
        page = 1
        while True:
            payload = self._get_json(
                f"/repos/{repository}/actions/runs/{run_id}/jobs?filter=all&per_page=100&page={page}"
            )
            batch = payload.get("jobs", [])
            if not isinstance(batch, list):
                raise GitHubAPIError("GitHub jobs response did not contain a jobs list")
            jobs.extend(batch)
            if len(batch) < 100:
                return jobs
            page += 1

    def job_log(self, repository: str, job_id: int) -> str:
        """Return one job's log text, decoded as UTF-8 with invalid bytes replaced."""
        _check_repository(repository)
        return self._request(f"/repos/{repository}/actions/jobs/{job_id}/logs").decode("utf-8", errors="replace")

    def collect_run(self, repository: str, run_id: int, *, include_logs: bool = True) -> WorkflowRunEvidence:
        """Collect normalized job metadata and failed-job logs for a workflow run."""
        if repository.count("/") != 1:
            raise ValueError("repository must use owner/name format")
        if run_id <= 0:
            raise ValueError("run_id must be a positive integer")

        payload = self._get_json(f"/repos/{repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100")
        jobs = payload.get("jobs", [])
        if not isinstance(jobs, list):
            raise GitHubAPIError("GitHub jobs response did not contain a jobs list")

        logs: dict[str, str] = {}
        if include_logs:
            failed = {"failure", "timed_out", "cancelled", "action_required"}
            for job in jobs:
                if job.get("conclusion") not in failed or not job.get("id"):
                    continue
                raw = self._request(
                    f"/repos/{repository}/actions/jobs/{job['id']}/logs",
                    accept="application/vnd.github+json",
                )
                logs[str(job.get("name", job["id"]))] = raw.decode("utf-8", errors="replace")

        return WorkflowRunEvidence(jobs=jobs, logs=logs)

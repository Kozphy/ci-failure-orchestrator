from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GitHubAPIError(RuntimeError):
    """Raised when GitHub Actions evidence cannot be collected safely."""


@dataclass(frozen=True)
class WorkflowRunEvidence:
    """Normalized jobs and logs collected from one GitHub Actions run."""

    jobs: list[dict]
    logs: dict[str, str]


class GitHubActionsClient:
    """Minimal GitHub REST client for workflow-run evidence collection.

    Authentication uses a bearer token supplied explicitly or via GITHUB_TOKEN.
    The client intentionally performs read-only requests.
    """

    def __init__(self, token: str | None = None, api_url: str = "https://api.github.com", timeout: float = 30.0):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, *, accept: str = "application/vnd.github+json") -> bytes:
        headers = {
            "Accept": accept,
            "User-Agent": "ci-failure-orchestrator",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(f"{self.api_url}{path}", headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
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

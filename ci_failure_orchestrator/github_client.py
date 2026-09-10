from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GitHubAPIError(RuntimeError):
    """Raised when GitHub evidence cannot be collected safely."""


@dataclass(frozen=True)
class WorkflowRunEvidence:
    """Normalized jobs and logs collected from one GitHub Actions run."""

    jobs: list[dict]
    logs: dict[str, str]


@dataclass(frozen=True)
class RepositoryEvidence:
    """Bounded repository-wide evidence used for deterministic health analysis."""

    metadata: dict
    tree: list[dict]
    files: dict[str, str]
    truncated: bool = False


class GitHubActionsClient:
    """Minimal read-only GitHub REST client for CI and repository evidence."""

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

    @staticmethod
    def _validate_repository(repository: str) -> None:
        if repository.count("/") != 1 or any(not part for part in repository.split("/")):
            raise ValueError("repository must use owner/name format")

    def collect_run(self, repository: str, run_id: int, *, include_logs: bool = True) -> WorkflowRunEvidence:
        """Collect normalized job metadata and failed-job logs for a workflow run."""
        self._validate_repository(repository)
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

    def collect_repository(self, repository: str, *, ref: str | None = None) -> RepositoryEvidence:
        """Collect bounded repository evidence without cloning the repository.

        The recursive Git tree provides the repository inventory. Only high-signal
        CI/build/governance files are fetched for content inspection so analysis
        remains deterministic and bounded on large repositories.
        """
        self._validate_repository(repository)
        metadata = self._get_json(f"/repos/{repository}")
        resolved_ref = ref or metadata.get("default_branch") or "main"
        tree_payload = self._get_json(
            f"/repos/{repository}/git/trees/{quote(str(resolved_ref), safe='')}?recursive=1"
        )
        tree = tree_payload.get("tree", [])
        if not isinstance(tree, list):
            raise GitHubAPIError("GitHub tree response did not contain a tree list")

        paths = [item.get("path", "") for item in tree if item.get("type") == "blob"]
        selected = [path for path in paths if self._is_repository_evidence_file(path)]
        files: dict[str, str] = {}
        for path in selected[:100]:
            payload = self._get_json(
                f"/repos/{repository}/contents/{quote(path, safe='/')}?ref={quote(str(resolved_ref), safe='')}"
            )
            content = payload.get("content")
            encoding = payload.get("encoding")
            if encoding == "base64" and isinstance(content, str):
                try:
                    files[path] = base64.b64decode(content, validate=False).decode("utf-8", errors="replace")
                except (ValueError, TypeError):
                    continue

        return RepositoryEvidence(
            metadata=metadata,
            tree=tree,
            files=files,
            truncated=bool(tree_payload.get("truncated")),
        )

    @staticmethod
    def _is_repository_evidence_file(path: str) -> bool:
        lower = path.lower()
        name = lower.rsplit("/", 1)[-1]
        exact = {
            "readme.md",
            "pyproject.toml",
            "requirements.txt",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "poetry.lock",
            "pipfile",
            "dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "security.md",
            "codeowners",
            "dependabot.yml",
            "dependabot.yaml",
            ".pre-commit-config.yaml",
            ".pre-commit-config.yml",
        }
        return (
            name in exact
            or lower.startswith(".github/workflows/") and lower.endswith((".yml", ".yaml"))
            or lower.endswith("/security.md")
            or lower.endswith("/codeowners")
            or lower.endswith("/dependabot.yml")
            or lower.endswith("/dependabot.yaml")
        )

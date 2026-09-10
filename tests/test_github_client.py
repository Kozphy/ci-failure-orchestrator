from __future__ import annotations

import base64
import json

import pytest

from ci_failure_orchestrator.github_client import GitHubActionsClient


def test_collect_run_validates_repository_and_run_id():
    client = GitHubActionsClient(token="test")
    with pytest.raises(ValueError, match="owner/name"):
        client.collect_run("invalid", 1)
    with pytest.raises(ValueError, match="positive"):
        client.collect_run("owner/repo", 0)


def test_collect_run_fetches_failed_job_logs(monkeypatch):
    client = GitHubActionsClient(token="test")
    seen = []

    def fake_request(path, *, accept="application/vnd.github+json"):
        seen.append((path, accept))
        if "/actions/runs/42/jobs" in path:
            return json.dumps(
                {
                    "jobs": [
                        {"id": 100, "name": "tests", "conclusion": "failure"},
                        {"id": 101, "name": "lint", "conclusion": "success"},
                    ]
                }
            ).encode()
        if "/actions/jobs/100/logs" in path:
            return b"ModuleNotFoundError: No module named 'requests'"
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", fake_request)
    evidence = client.collect_run("owner/repo", 42)

    assert [job["name"] for job in evidence.jobs] == ["tests", "lint"]
    assert evidence.logs == {"tests": "ModuleNotFoundError: No module named 'requests'"}
    assert not any("/actions/jobs/101/logs" in path for path, _ in seen)


def test_collect_run_can_skip_logs(monkeypatch):
    client = GitHubActionsClient(token="test")

    def fake_request(path, *, accept="application/vnd.github+json"):
        assert "/actions/runs/7/jobs" in path
        return json.dumps({"jobs": [{"id": 1, "name": "tests", "conclusion": "failure"}]}).encode()

    monkeypatch.setattr(client, "_request", fake_request)
    evidence = client.collect_run("owner/repo", 7, include_logs=False)

    assert evidence.logs == {}


def test_collect_repository_fetches_tree_and_bounded_evidence(monkeypatch):
    client = GitHubActionsClient(token="test")
    requested = []

    def fake_request(path, *, accept="application/vnd.github+json"):
        requested.append(path)
        if path == "/repos/owner/repo":
            return json.dumps({"full_name": "owner/repo", "default_branch": "main"}).encode()
        if "/git/trees/main?recursive=1" in path:
            return json.dumps(
                {
                    "truncated": False,
                    "tree": [
                        {"path": "README.md", "type": "blob"},
                        {"path": "pyproject.toml", "type": "blob"},
                        {"path": ".github/workflows/ci.yml", "type": "blob"},
                        {"path": "ci_failure_orchestrator/cli.py", "type": "blob"},
                    ],
                }
            ).encode()
        if "/contents/" in path:
            file_path = path.split("/contents/", 1)[1].split("?ref=", 1)[0]
            text = f"content for {file_path}"
            return json.dumps(
                {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}
            ).encode()
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", fake_request)
    evidence = client.collect_repository("owner/repo")

    assert evidence.metadata["default_branch"] == "main"
    assert evidence.truncated is False
    assert set(evidence.files) == {"README.md", "pyproject.toml", ".github/workflows/ci.yml"}
    assert not any("ci_failure_orchestrator/cli.py?" in path for path in requested)


def test_collect_repository_validates_repository():
    client = GitHubActionsClient(token="test")
    with pytest.raises(ValueError, match="owner/name"):
        client.collect_repository("owner-only")

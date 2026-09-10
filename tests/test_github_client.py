from __future__ import annotations

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

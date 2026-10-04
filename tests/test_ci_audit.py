from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from urllib.request import Request

import pytest

from ci_failure_orchestrator import cli
from ci_failure_orchestrator.ci_audit import EXPORT_SCHEMA, analyze_export, collect_export, render_report
from ci_failure_orchestrator.ci_audit.analyze import job_minutes, percentile
from ci_failure_orchestrator.ci_audit.collect import (
    classify_failure,
    failing_section,
    failure_message,
    runner_os,
    workflow_label,
)
from ci_failure_orchestrator.github_client import GitHubActionsClient, GitHubAPIError, _DropAuthOnCrossHostRedirect

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


def _iso(minutes: float) -> str:
    return (datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _run(run_id, workflow_id, name, sha, event, conclusion, *, attempt=1, at=0, status="completed"):
    return {
        "id": run_id, "workflow_id": workflow_id, "name": name, "event": event, "head_branch": "main",
        "head_sha": sha, "status": status, "conclusion": conclusion, "run_attempt": attempt,
        "created_at": _iso(at), "run_started_at": _iso(at + 1), "updated_at": _iso(at + 11),
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}", "repository": {"private": False},
    }


def _job(job_id, run_id, name, conclusion, minutes, *, attempt=1, at=0, labels=("ubuntu-latest",), step=""):
    steps = [{"name": step, "conclusion": conclusion}] if step else []
    return {
        "id": job_id, "run_id": run_id, "run_attempt": attempt, "name": name, "conclusion": conclusion,
        "started_at": _iso(at), "completed_at": _iso(at + minutes), "labels": list(labels), "steps": steps,
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}/job/{job_id}",
    }


RUNS = [
    _run(101, 1, "CI", "aaa", "pull_request", "success", attempt=2, at=0),
    _run(102, 1, "CI", "bbb", "push", "success", at=20),
    _run(103, 1, "CI", "bbb", "pull_request", "success", at=21),
    _run(104, 1, "CI", "ccc", "pull_request", "failure", at=40),
    _run(105, 1, "CI", "ccc", "pull_request", "success", at=60),
    _run(106, 1, "CI", "ddd", "pull_request", None, at=80, status="in_progress"),
    _run(201, 2, "Build", "eee", "push", "failure", at=90),
]
JOBS = {
    101: [_job(1, 101, "test", "failure", 5, attempt=1, step="pytest"), _job(2, 101, "test", "success", 5, attempt=2, at=10)],
    102: [_job(3, 102, "test", "success", 4, at=20), _job(4, 102, "windows", "success", 10, at=20, labels=("windows-latest",))],
    103: [_job(5, 103, "test", "success", 4, at=21)],
    104: [_job(6, 104, "lint", "failure", 1, at=40, step="Ruff")],
    105: [_job(7, 105, "lint", "success", 2, at=60)],
    201: [_job(8, 201, "docker", "failure", 3, at=90, step="Install")],
}
LOGS = {
    6: f"2026-09-20T10:40:01Z ruff check .\nerror: F401 unused import token={TOKEN}\n",
    8: "Traceback (most recent call last):\nModuleNotFoundError: No module named 'requests'\n",
    1: "FAILED tests/test_calc.py::test_add - AssertionError\n",
}


class FakeReader:
    def __init__(self):
        self.job_calls: list[int] = []
        self.log_calls: list[int] = []

    def list_workflow_runs(self, repository, *, created_since, max_runs):
        assert created_since == "2026-08-31"
        return RUNS[:max_runs]

    def list_run_jobs(self, repository, run_id):
        self.job_calls.append(run_id)
        return JOBS.get(run_id, [])

    def job_log(self, repository, job_id):
        self.log_calls.append(job_id)
        if job_id not in LOGS:
            raise GitHubAPIError("HTTP 410")
        return LOGS[job_id]


@pytest.fixture
def export():
    return collect_export(FakeReader(), "o/r", days=30, now=NOW)


def test_collect_skips_in_progress_runs_and_scrubs_secrets(export):
    assert export["schema"] == EXPORT_SCHEMA
    assert export["private"] is False
    assert len(export["runs"]) == 7
    assert {job["run_id"] for job in export["jobs"]} == {101, 102, 103, 104, 105, 201}
    assert len(export["failures"]) == 3
    assert TOKEN not in json.dumps(export)
    by_job = {f["job_id"]: f for f in export["failures"]}
    assert by_job[6]["category"] == "lint_failure"
    assert by_job[8]["category"] == "dependency_failure"
    assert all(len(f["message"]) <= 300 for f in export["failures"])


def test_collect_fetches_only_most_recent_logs():
    reader = FakeReader()
    export = collect_export(reader, "o/r", days=30, max_logs=1, now=NOW)
    assert reader.log_calls == [8]
    assert sum(1 for f in export["failures"] if f["log_available"]) == 1


def test_collect_rejects_bad_limits():
    with pytest.raises(ValueError):
        collect_export(FakeReader(), "o/r", days=0, now=NOW)


def test_analysis_metrics(export):
    a = analyze_export(export)
    t, waste = a["totals"], a["waste"]
    assert (t["completed"], t["in_progress"]) == (6, 1)
    assert (t["succeeded"], t["failed"]) == (4, 2)
    assert t["failure_rate"] == pytest.approx(0.333)
    assert t["rerun_runs"] == 1
    assert t["flaky_groups"] == 2
    assert {r["kind"] for r in a["flaky"]} == {"rerun_passed", "fail_then_pass_same_commit"}
    assert a["os_minutes"]["windows"] == 20
    assert t["billed_minutes"] == 5 + 5 + 4 + 20 + 4 + 1 + 2 + 3
    assert waste["duplicate_runs"] == 1
    assert waste["duplicate_minutes"] == 4
    assert waste["rerun_minutes"] == 5
    assert waste["failed_minutes"] == 5 + 1 + 3


def test_findings_are_ranked_by_severity(export):
    findings = analyze_export(export)["findings"]
    ids = [f["id"] for f in findings]
    assert {"F-OS", "F-DUP", "F-FLAKY"} <= set(ids)
    assert "F-FAIL" not in ids  # only 2 failures; the rule needs at least 5 to avoid small-sample noise
    severities = [f["severity"] for f in findings]
    assert severities == sorted(severities, key={"High": 0, "Medium": 1, "Low": 2}.get)
    assert next(f for f in findings if f["id"] == "F-OS")["severity"] == "High"


def test_report_has_every_section_and_no_secrets(export):
    report = render_report(analyze_export(export))
    for number in range(1, 14):
        assert f"## {number}. " in report
    assert "Public repository" in report
    assert TOKEN not in report
    assert "https://github.com/o/r/actions/runs/104/job/6" in report


def test_analyze_rejects_unknown_schema():
    with pytest.raises(ValueError):
        analyze_export({"schema": "other"})


def test_minutes_and_runner_os():
    assert runner_os(["windows-2022"]) == "windows"
    assert runner_os(["macos-14"]) == "macos"
    assert runner_os(["self-hosted", "linux"]) == "self-hosted"
    assert runner_os([]) == "linux"
    assert job_minutes({"started_at": _iso(0), "completed_at": _iso(1.2), "runner_os": "macos"}) == (2, 20)
    assert job_minutes({"started_at": None, "completed_at": None, "runner_os": "linux"}) == (0, 0)
    assert percentile([1, 2, 3, 4], 50) == 2
    assert percentile([], 90) == 0.0


def test_collect_reports_log_download_failures():
    class NoLogs(FakeReader):
        def job_log(self, repository, job_id):
            raise GitHubAPIError("HTTP 401: blob storage rejected the request")

    export = collect_export(NoLogs(), "o/r", days=30, now=NOW)
    assert any("3 failed-job logs could not be downloaded" in w for w in export["warnings"])
    analysis = analyze_export(export)
    assert analysis["logs_missing"] == 3
    assert "F-SIGNAL" not in {f["id"] for f in analysis["findings"]}


REAL_SHAPED_LOG = """2026-09-28T09:49:40.1Z ##[group]Run actions/checkout@v4
2026-09-28T09:49:40.2Z ##[endgroup]
2026-09-28T09:49:41.0Z ##[group]Run python -m ruff check src
2026-09-28T09:49:41.1Z python -m ruff check src
2026-09-28T09:49:41.1Z echo "install dependency cache"
2026-09-28T09:49:41.2Z ##[endgroup]
2026-09-28T09:49:42.0Z 18 | from .provenance import DependencyProvenanceEvaluator
2026-09-28T09:49:42.1Z Found 1 error.
2026-09-28T09:49:42.2Z ##[error]Process completed with exit code 1.
2026-09-28T09:49:43.0Z Post job cleanup.
2026-09-28T09:49:43.1Z [command]/usr/bin/git config --local --unset includeif.gitdir:/home/runner/work/ci-failure-x/.git.path
"""


def test_failing_section_keeps_only_the_failing_step_output():
    section = failing_section(REAL_SHAPED_LOG)
    assert section.splitlines()[0] == "##[group]Run python -m ruff check src"
    assert "install dependency cache" not in section
    assert "git config" not in section
    assert section.splitlines()[-1] == "##[error]Process completed with exit code 1."
    assert failure_message(section) == "Found 1 error."


def test_failure_message_prefers_specific_error_then_warning():
    assert failure_message("##[error]ENOENT: no such file\n##[error]Process completed with exit code 2.") == "ENOENT: no such file"
    assert failure_message("scanning\n##[warning]Leaks detected, see job summary") == "Leaks detected, see job summary"


def test_audit_refinement_does_not_hide_real_dependency_failures():
    job = {"id": 1, "run_id": 1, "run_attempt": 1, "name": "lint", "failed_step": "Run ruff", "html_url": ""}
    lint = classify_failure("CI", job, REAL_SHAPED_LOG)
    assert (lint["category"], lint["classified_by"]) == ("lint_failure", "step")
    missing = classify_failure("CI", {**job, "name": "test", "failed_step": "Run pytest"}, "##[group]Run pytest\n##[endgroup]\nModuleNotFoundError: No module named 'requests'\n##[error]Process completed with exit code 1.")
    assert missing["category"] == "dependency_failure"
    scan = classify_failure("CI", {**job, "name": "Gitleaks", "failed_step": "Run gitleaks/gitleaks-action@v2"}, "##[warning]Leaks detected")
    assert scan["category"] == "security_scan_failure"


def test_dependabot_dynamic_runs_share_one_workflow_label():
    assert workflow_label({"name": "pip in /. - Update #123", "path": "dynamic/dependabot/dependabot-updates"}) == "dependabot-updates (dynamic)"
    assert workflow_label({"name": "CI", "path": ".github/workflows/ci.yml"}) == "CI"


def test_log_redirect_to_another_host_drops_the_token():
    handler = _DropAuthOnCrossHostRedirect()
    request = Request("https://api.github.com/repos/o/r/actions/jobs/1/logs", headers={"Authorization": "Bearer secret"})
    blob = handler.redirect_request(request, None, 302, "Found", {}, "https://blob.example.net/log.txt?sig=x")
    assert blob is not None and not blob.has_header("Authorization")
    same = handler.redirect_request(request, None, 302, "Found", {}, "https://api.github.com/other")
    assert same is not None and same.get_header("Authorization") == "Bearer secret"


def test_client_paginates_and_caps_runs(monkeypatch):
    client = GitHubActionsClient(token="t")
    pages = {1: [{"id": i} for i in range(100)], 2: [{"id": i} for i in range(100, 130)]}
    seen: list[str] = []

    def fake_get(path):
        seen.append(path)
        page = int(path.rsplit("page=", 1)[1])
        return {"workflow_runs": pages.get(page, [])}

    monkeypatch.setattr(client, "_get_json", fake_get)
    assert len(client.list_workflow_runs("o/r", created_since="2026-09-01", max_runs=500)) == 130
    assert "created=%3E%3D2026-09-01" in seen[0]
    seen.clear()
    assert len(client.list_workflow_runs("o/r", created_since="2026-09-01", max_runs=50)) == 50
    assert len(seen) == 1
    with pytest.raises(ValueError):
        client.list_run_jobs("not-a-repo", 1)


def test_cli_report_round_trip(tmp_path, monkeypatch, export):
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps(export), encoding="utf-8")
    out = tmp_path / "report.md"
    analysis = tmp_path / "analysis.json"
    monkeypatch.setattr(sys, "argv", ["ci-orchestrator", "ci-audit-report", str(export_path), "--output", str(out), "--json", str(analysis)])
    assert cli.main() == 0
    assert out.read_text(encoding="utf-8").startswith("# GitHub CI Reliability Audit: `o/r`")
    assert json.loads(analysis.read_text(encoding="utf-8"))["totals"]["failed"] == 2

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "nope"}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ci-orchestrator", "ci-audit-report", str(bad)])
    assert cli.main() == 2


def test_cli_collect_writes_export(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "GitHubActionsClient", lambda **kwargs: FakeReader())
    monkeypatch.setattr(cli, "collect_export", lambda reader, repo, **kw: collect_export(reader, repo, now=NOW, **kw))
    out = tmp_path / "export.json"
    monkeypatch.setattr(sys, "argv", ["ci-orchestrator", "ci-audit-collect", "--repo", "o/r", "--output", str(out)])
    assert cli.main() == 0
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == EXPORT_SCHEMA

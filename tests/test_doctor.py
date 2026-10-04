from __future__ import annotations

import json

import pytest

from ci_failure_orchestrator.doctor import diagnose_log, diagnose_run, render_text
from ci_failure_orchestrator.doctor.cli import EXIT_INPUT, main, parse_run_url
from ci_failure_orchestrator.foundation.policy import RULE_FAILURE_CATEGORY
from ci_failure_orchestrator.github_client import GitHubAPIError

TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
TS = "2026-10-04T10:00:00.0000000Z "

PIP_LOG = "\n".join(
    TS + line
    for line in [
        "##[group]Run actions/checkout@v4",
        "##[endgroup]",
        "##[group]Run pip install -r requirements.txt",
        "pip install -r requirements.txt",
        "shell: /usr/bin/bash -e {0}",
        "##[endgroup]",
        "Collecting requests==2.32.3",
        (
            "ERROR: Cannot install requests==2.32.3 and urllib3==1.26.20 because these package versions have "
            "conflicting dependencies."
        ),
        "ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/topics/dependency-resolution/",
        "##[error]Process completed with exit code 1.",
        "Post job cleanup.",
        "[command]/usr/bin/git config --local --unset-all http.extraheader",
    ]
)

PYTEST_LOG = (
    "##[group]Run pytest -q\n"
    "pytest -q\n"
    "##[endgroup]\n"
    "FAILED tests/test_calc.py::test_add - AssertionError: assert 3 == 4\n"
    "1 failed, 4 passed in 0.12s\n"
    "##[error]Process completed with exit code 1."
)

GITLEAKS_LOG = (
    "##[group]Run gitleaks/gitleaks-action@v3\n"
    "with:\n"
    "##[endgroup]\n"
    "##[error]Leaks detected, see job summary for details"
)


def test_offline_log_dependency_conflict_cites_the_resolver_line():
    d = diagnose_log(PIP_LOG, job="tests")
    top = d.findings[0]

    # The job is called "tests", but the failing step ran pip: the step decides, not the job name.
    assert top.category == "dependency_failure"
    assert top.message.startswith("ERROR: Cannot install requests==2.32.3")
    assert top.evidence_line == 8
    assert top.command == "pip install -r requirements.txt"
    assert top.confidence == "medium"  # the evidence is a tool line, not a specific ##[error] line
    assert d.policy is not None and d.policy.outcome == "ESCALATE"
    assert d.policy.rules == (RULE_FAILURE_CATEGORY,)
    assert d.verification == ("pip install -r requirements.txt",)
    assert d.diagnosis_id == diagnose_log(PIP_LOG, job="tests").diagnosis_id
    assert d.diagnosis_id.startswith("CID-log-")


def test_test_failure_is_eligible_and_recommends_worktree_verification():
    d = diagnose_log(PYTEST_LOG, job="unit")
    top = d.findings[0]

    assert top.category == "test_failure"
    assert top.message == "FAILED tests/test_calc.py::test_add - AssertionError: assert 3 == 4"
    assert top.evidence_line == 4
    assert d.policy is not None and d.policy.outcome == "ELIGIBLE"
    text = render_text(d)
    assert 'ci-orchestrator fix-repo --repo-path . --verify "pytest -q" --patch-file fix.diff' in text
    assert "No category or confidence rule blocks an automated repair." in text


def test_action_step_is_not_offered_as_a_command_and_security_gets_no_code_fix():
    d = diagnose_log(GITLEAKS_LOG, job="Gitleaks")
    top = d.findings[0]

    assert top.category == "security_scan_failure"
    assert top.command == ""
    assert top.confidence == "medium"
    assert d.verification == ("re-run the failed job",)
    text = " ".join(render_text(d).split())
    assert "does not propose code changes for security findings" in text
    assert "fix-repo" not in text
    assert f"The engine decides on its own category, {top.policy_category}" in text


def test_specific_error_line_gives_high_confidence():
    log = "##[group]Run mypy .\n##[endgroup]\n##[error]src/app.py:3: error: Incompatible types in assignment\n"
    top = diagnose_log(log).findings[0]

    assert top.category == "type_failure"
    assert (top.confidence, top.evidence_line) == ("high", 3)


def test_unknown_failure_says_so_and_escalates():
    d = diagnose_log("##[group]Run ./build.sh\n##[endgroup]\nsomething odd happened\n")
    top = d.findings[0]

    assert top.category == "unknown"
    assert top.confidence == "low"
    assert d.policy is not None and d.policy.outcome == "ESCALATE"
    assert "No rule matched" in d.next_step


def test_tokens_in_logs_never_reach_output():
    log = PYTEST_LOG.replace("assert 3 == 4", f"token={TOKEN}")
    d = diagnose_log(log)

    assert TOKEN not in render_text(d)
    assert TOKEN not in json.dumps(d.to_dict())


def _job(job_id, name, conclusion, *, attempt=1, start="10:00", step="", labels=("ubuntu-latest",)):
    return {
        "id": job_id,
        "run_id": 77,
        "run_attempt": attempt,
        "name": name,
        "conclusion": conclusion,
        "started_at": f"2026-10-04T{start}:00Z",
        "completed_at": f"2026-10-04T{start}:30Z",
        "labels": list(labels),
        "steps": [{"name": step, "conclusion": conclusion}] if step else [],
        "html_url": f"https://github.com/o/r/actions/runs/77/job/{job_id}",
    }


class FakeReader:
    def __init__(self, jobs, logs):
        self.jobs = jobs
        self.logs = logs
        self.log_calls: list[int] = []

    def get_run(self, repository, run_id):
        return {
            "id": run_id,
            "name": "CI",
            "path": ".github/workflows/ci.yml",
            "head_sha": "3f2a9c1e0000",
            "html_url": f"https://github.com/{repository}/actions/runs/{run_id}",
            "conclusion": "failure",
            "created_at": "2026-10-04T09:59:00Z",
            "run_attempt": 2,
        }

    def list_run_jobs(self, repository, run_id):
        return self.jobs

    def job_log(self, repository, job_id):
        self.log_calls.append(job_id)
        if job_id not in self.logs:
            raise GitHubAPIError("GitHub API returned HTTP 404: BlobNotFound")
        return self.logs[job_id]


JOBS = [
    _job(1, "unit", "failure", attempt=1, step="pytest"),
    _job(2, "unit", "failure", attempt=2, start="10:05", step="Install dependencies"),
    _job(3, "package", "failure", attempt=2, start="10:01", step="Mystery"),
    _job(4, "integration", "skipped", attempt=2, start="10:06"),
    _job(5, "docs", "success", attempt=2, start="10:00"),
]


def test_run_uses_latest_attempt_ranks_known_causes_first_and_lists_skipped_jobs():
    reader = FakeReader(JOBS, {2: PIP_LOG, 3: "##[group]Run ./odd.sh\n##[endgroup]\nhmm\n"})
    d = diagnose_run(reader, "o/r", 77)

    assert d.run_attempt == 2
    assert 1 not in reader.log_calls  # attempt 1 is not diagnosed
    assert [(f.job, f.category) for f in d.findings] == [("unit", "dependency_failure"), ("package", "unknown")]
    assert d.findings[0].category == "dependency_failure"
    assert d.findings[0].rank_reason == "2nd failed job in run order"
    assert d.findings[1].rank_reason == "1st failed job in run order; no rule matched the log"
    assert d.affected == (("integration", "skipped"),)
    assert d.diagnosis_id.startswith("CID-20261004-")
    assert d.head_sha.startswith("3f2a9c1")
    text = render_text(d)
    assert "Root-cause candidates" in text
    assert "1. unit > Install dependencies   dependency_failure" in text


def test_run_attempt_and_job_filters():
    reader = FakeReader(JOBS, {1: PYTEST_LOG})
    d = diagnose_run(reader, "o/r", 77, attempt=1, job="unit")

    assert d.run_attempt == 1
    assert [f.category for f in d.findings] == ["test_failure"]


def test_missing_logs_and_log_cap_become_warnings_not_guesses():
    reader = FakeReader(JOBS, {})
    d = diagnose_run(reader, "o/r", 77, max_logs=1)

    assert len(reader.log_calls) == 1
    assert all(not f.log_available for f in d.findings)
    assert any("unavailable" in w and "BlobNotFound" in w for w in d.warnings)
    assert any("not read (limit of 1 logs)" in w for w in d.warnings)
    assert "log not available" in render_text(d)


def test_run_without_failed_jobs_has_nothing_to_diagnose():
    reader = FakeReader([_job(5, "docs", "success")], {})
    d = diagnose_run(reader, "o/r", 77)

    assert d.findings == () and d.policy is None
    assert "Nothing to diagnose." in render_text(d)
    assert "no failed jobs in attempt 1" in d.warnings[0]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/o/r/actions/runs/123", ("o/r", 123, None)),
        ("https://github.com/o/r.js/actions/runs/123/attempts/2", ("o/r.js", 123, 2)),
        ("https://github.com/o/r/actions/runs/123/", ("o/r", 123, None)),
    ],
)
def test_parse_run_url(url, expected):
    assert parse_run_url(url) == expected


def test_parse_run_url_rejects_other_urls():
    with pytest.raises(ValueError):
        parse_run_url("https://github.com/o/r/pull/5")


def test_cli_log_round_trip_text_json_and_out(tmp_path, capsys):
    log = tmp_path / "tests.log"
    log.write_text(PIP_LOG, encoding="utf-8")

    assert main(["analyze", "--log", str(log)]) == 0
    text = capsys.readouterr().out
    assert text.startswith("CI Doctor | analyze | saved log")
    assert 'job "tests" > log line 8' in text

    out = tmp_path / "out"
    assert main(["analyze", "--log", str(log), "--json", "--out", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    saved = json.loads((out / "diagnosis.json").read_text(encoding="utf-8"))
    assert printed == saved
    assert saved["schema"] == "actions-doctor.diagnosis.v1"
    assert saved["findings"][0]["category"] == "dependency_failure"


def test_cli_errors(tmp_path, capsys):
    assert main(["analyze", "--log", str(tmp_path / "missing.log")]) == EXIT_INPUT
    assert "cannot read" in capsys.readouterr().err
    with pytest.raises(SystemExit) as usage:
        main(["analyze", "--repo", "o/r"])
    assert usage.value.code == 2
    with pytest.raises(SystemExit):
        main(["analyze", "--url", "https://github.com/o/r/pull/5"])


def test_cli_github_errors_exit_3_without_leaking_the_token(monkeypatch, capsys):
    def boom(self, repository, run_id):
        raise GitHubAPIError(f"GitHub API returned HTTP 401: bad credentials {TOKEN}")

    monkeypatch.setattr("ci_failure_orchestrator.github_client.GitHubActionsClient.get_run", boom)
    assert main(["analyze", "--repo", "o/r", "--run", "5", "--token", TOKEN]) == EXIT_INPUT
    captured = capsys.readouterr()
    assert "HTTP 401" in captured.err
    assert TOKEN not in captured.err + captured.out

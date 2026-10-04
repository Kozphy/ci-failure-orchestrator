from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from ci_failure_orchestrator.doctor.action import main
from ci_failure_orchestrator.doctor.cli import EXIT_INPUT, EXIT_OK, EXIT_USAGE
from ci_failure_orchestrator.github_client import GitHubAPIError

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
PYTEST_LOG = (
    "##[group]Run pytest -q\n"
    "pytest -q\n"
    "##[endgroup]\n"
    "FAILED tests/test_calc.py::test_add - AssertionError: assert 3 == 4\n"
    "1 failed, 4 passed in 0.12s\n"
    "##[error]Process completed with exit code 1."
)


class Reader:
    def __init__(self, conclusion="failure", log=PYTEST_LOG, error=None):
        self.conclusion = conclusion
        self.log = log
        self.error = error

    def get_run(self, repository, run_id):
        if self.error:
            raise self.error
        return {
            "id": run_id,
            "name": "ci",
            "path": ".github/workflows/ci.yml",
            "head_sha": "3f2a9c1e0000",
            "html_url": f"https://github.com/{repository}/actions/runs/{run_id}",
            "conclusion": self.conclusion,
            "created_at": "2026-10-04T09:59:00Z",
            "run_attempt": 1,
        }

    def list_run_jobs(self, repository, run_id):
        return [
            {
                "id": 1,
                "run_attempt": 1,
                "name": "test",
                "conclusion": self.conclusion,
                "started_at": "2026-10-04T10:00:00Z",
                "completed_at": "2026-10-04T10:00:30Z",
                "labels": ["ubuntu-latest"],
                "steps": [{"name": "Run tests", "conclusion": self.conclusion}],
                "html_url": f"https://github.com/{repository}/actions/runs/{run_id}/job/1",
            }
        ]

    def job_log(self, repository, job_id):
        return self.log


def _env(tmp_path, **overrides):
    env = {
        "CI_DOCTOR_REPOSITORY": "o/r",
        "CI_DOCTOR_RUN_ID": "77",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
    }
    env.update(overrides)
    return env


def _outputs(tmp_path):
    return dict(line.split("=", 1) for line in (tmp_path / "output.txt").read_text(encoding="utf-8").splitlines())


def test_failed_run_writes_log_summary_outputs_and_diagnosis_file(tmp_path, capsys):
    assert main(_env(tmp_path), reader=Reader()) == EXIT_OK

    stdout = capsys.readouterr().out
    assert stdout.startswith("CI Doctor | analyze | o/r | run 77")
    assert "test_failure" in stdout

    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert summary.startswith("## CI Doctor: test_failure\n\n[Run 77](https://github.com/o/r/actions/runs/77)")
    assert "FAILED tests/test_calc.py::test_add" in summary

    outputs = _outputs(tmp_path)
    assert outputs["failure-class"] == "test_failure"
    diagnosis = json.loads(Path(outputs["diagnosis-file"]).read_text(encoding="utf-8"))
    assert diagnosis["run_id"] == 77
    assert diagnosis["findings"][0]["job"] == "test"


def test_run_without_failures_succeeds_with_failure_class_none(tmp_path, capsys):
    assert main(_env(tmp_path), reader=Reader(conclusion="success")) == EXIT_OK

    assert "Nothing to diagnose." in capsys.readouterr().out
    assert (tmp_path / "summary.md").read_text(encoding="utf-8").startswith("## CI Doctor: nothing to diagnose")
    assert _outputs(tmp_path)["failure-class"] == "none"


def test_hostile_log_cannot_issue_workflow_commands_or_break_the_summary_fence(tmp_path, capsys):
    log = f"##[group]Run ./build.sh\n##[endgroup]\n##[error]::add-mask::```` token={TOKEN}\n"
    assert main(_env(tmp_path), reader=Reader(log=log)) == EXIT_OK

    stdout = capsys.readouterr().out
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "[neutralized] ::add-mask::````" in stdout
    assert not re.search(r"^\s*::", stdout, re.MULTILINE)
    assert TOKEN not in stdout and TOKEN not in summary
    fence_lines = [line for line in summary.splitlines() if line.startswith("`")]
    assert len(fence_lines) == 2 and fence_lines[0] == "`````text" and fence_lines[1] == "`````"


def test_missing_or_malformed_inputs_fail_before_any_api_call(tmp_path, capsys):
    reader = Reader(error=AssertionError("must not be called"))

    assert main(_env(tmp_path, CI_DOCTOR_RUN_ID=""), reader=reader) == EXIT_USAGE
    assert main(_env(tmp_path, CI_DOCTOR_RUN_ID="12; rm -rf /"), reader=reader) == EXIT_USAGE
    assert main(_env(tmp_path, CI_DOCTOR_REPOSITORY="o/r\n::error::x"), reader=reader) == EXIT_USAGE

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3 and all(line.startswith("::error title=CI Doctor::") for line in lines)
    assert not (tmp_path / "summary.md").exists()


def test_api_error_is_one_annotation_without_the_token(tmp_path, capsys):
    error = GitHubAPIError(f"GitHub API returned HTTP 404: Not Found\nAuthorization: Bearer {TOKEN}")

    assert main(_env(tmp_path), reader=Reader(error=error)) == EXIT_INPUT

    out = capsys.readouterr().out
    assert out.startswith("::error title=CI Doctor::cannot read run 77 of o/r: GitHub API returned HTTP 404")
    assert out.count("\n") == 1 and TOKEN not in out


def _steps_with_run(document):
    return [step for step in document["runs"]["steps"] if "run" in step]


def test_action_metadata_never_interpolates_expressions_into_shell():
    action = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))

    assert action["runs"]["using"] == "composite"
    assert {"run-id", "repository", "github-token"} <= set(action["inputs"])
    steps = _steps_with_run(action)
    assert steps
    for step in steps:
        assert "${{" not in step["run"], f"step {step.get('id')} interpolates an expression into its script"
        assert step["shell"] == "bash"
    diagnose = next(step for step in steps if step.get("id") == "diagnose")
    assert "ci_failure_orchestrator.doctor.action" in diagnose["run"]


def test_self_test_workflow_is_read_only_and_never_runs_the_failed_code():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci-doctor.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    ci_name = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["name"]

    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    assert triggers["workflow_run"]["workflows"] == [ci_name]
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    steps = workflow["jobs"]["diagnose"]["steps"]
    checkout = next(step for step in steps if str(step.get("uses", "")).startswith("actions/checkout"))
    assert "with" not in checkout  # default ref: the trusted default branch, not the failed run's head

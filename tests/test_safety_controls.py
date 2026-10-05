"""Safety controls on the write path: dry run, rollback, attempt ceiling and timeouts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import ci_failure_orchestrator.service.apply as apply_module
from ci_failure_orchestrator.foundation.persistence import AuditEventType, FileAuditStore
from ci_failure_orchestrator.service import FixRepoConfig, common, run_fix_repo
from ci_failure_orchestrator.service.apply import apply_fix
from ci_failure_orchestrator.service.run import MAX_ATTEMPTS_CEILING

BUGGY = "def add(a, b):\n    return a - b\n"
FIX_PATCH = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
VERIFY = f'"{sys.executable}" -c "import calc; assert calc.add(2, 3) == 5"'


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "calc.py").write_bytes(BUGGY.encode("utf-8"))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def _config(tmp_path: Path, repo: Path, **overrides) -> FixRepoConfig:
    patch = tmp_path / "fix.patch"
    patch.write_bytes(FIX_PATCH.encode("utf-8"))
    values = {
        "repo_path": repo,
        "verify_commands": [VERIFY],
        "patch_file": patch,
        "artifacts_root": tmp_path / "artifacts",
        "verify_timeout": 120,
    }
    values.update(overrides)
    return FixRepoConfig(**values)


def _approved_run(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = _repo(tmp_path)
    outcome = run_fix_repo(_config(tmp_path, repo))
    assert outcome["outcome"] == "APPROVED", outcome
    return repo, tmp_path / "artifacts", outcome["run_id"]


def _applied_events(artifacts: Path, run_id: str) -> list[str]:
    events, _ = FileAuditStore(artifacts).read_events_tolerant(run_id)
    return [e.event_type for e in events if e.event_type == AuditEventType.TARGET_PATCH_APPLIED.value]


def test_dry_run_checks_every_gate_and_writes_nothing(tmp_path):
    repo, artifacts, run_id = _approved_run(tmp_path)
    refs_before = _git(repo, "for-each-ref")
    objects_before = _git(repo, "count-objects", "-v")

    result = apply_fix(artifacts, run_id, dry_run=True, push=True)

    assert result.status == "DRY_RUN", result.message
    assert result.files == ["calc.py"]
    assert "push" in result.message and not result.pushed
    assert _git(repo, "for-each-ref") == refs_before
    assert _git(repo, "count-objects", "-v") == objects_before
    assert _applied_events(artifacts, run_id) == []
    # A dry run does not consume the run: the real apply still goes ahead.
    assert apply_fix(artifacts, run_id).status == "APPLIED"


def test_dry_run_still_refuses_a_protected_branch(tmp_path):
    _, artifacts, run_id = _approved_run(tmp_path)
    result = apply_fix(artifacts, run_id, branch="main", dry_run=True)
    assert result.status == "BLOCKED"
    assert "protected branch" in result.message


def test_apply_returns_rollback_commands_that_undo_it(tmp_path):
    repo, artifacts, run_id = _approved_run(tmp_path)
    result = apply_fix(artifacts, run_id, branch="fix/calc")

    assert result.status == "APPLIED"
    assert result.rollback == [f"git -C {repo} branch -D fix/calc"]
    _git(repo, "branch", "-D", "fix/calc")
    assert "fix/calc" not in _git(repo, "branch", "--list")


@pytest.mark.parametrize("attempts", [0, MAX_ATTEMPTS_CEILING + 1])
def test_attempt_budget_outside_the_ceiling_is_refused(tmp_path, attempts):
    outcome = run_fix_repo(_config(tmp_path, _repo(tmp_path), max_attempts=attempts))
    assert outcome["outcome"] == "ERROR"
    assert "--max-attempts" in outcome["message"]


def test_git_helper_reports_a_timeout_instead_of_raising(tmp_path, monkeypatch):
    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(common.subprocess, "run", hang)
    done = common.git(tmp_path, "push", "origin", "x", timeout=5)
    assert done.returncode == 124
    assert "timed out after 5s" in done.stderr


def _fake_remote(monkeypatch, *, push_returncode: int) -> None:
    real_git = apply_module.git

    def git(repo, *args, **kwargs):
        if args[:1] == ("ls-remote",):
            return subprocess.CompletedProcess(["git", *args], 0, "", "")
        if args[:1] == ("push",):
            stderr = "git push timed out after 300s" if push_returncode == 124 else ""
            return subprocess.CompletedProcess(["git", *args], push_returncode, "", stderr)
        return real_git(repo, *args, **kwargs)

    monkeypatch.setattr(apply_module, "git", git)


def test_push_timeout_is_partial_and_keeps_the_local_rollback(tmp_path, monkeypatch):
    repo, artifacts, run_id = _approved_run(tmp_path)
    _fake_remote(monkeypatch, push_returncode=124)

    result = apply_fix(artifacts, run_id, branch="fix/calc", push=True)

    assert result.status == "PARTIAL"
    assert "may have reached origin" in result.message
    assert result.rollback == [f"git -C {repo} branch -D fix/calc"]


def test_pr_creation_timeout_is_partial_with_push_rollback(tmp_path, monkeypatch):
    repo, artifacts, run_id = _approved_run(tmp_path)
    _fake_remote(monkeypatch, push_returncode=0)
    monkeypatch.setattr(apply_module.shutil, "which", lambda name: "gh")
    real_run = subprocess.run

    def hang_gh(argv, *args, **kwargs):
        if argv[0] == "gh":
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout"))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", hang_gh)

    result = apply_fix(artifacts, run_id, branch="fix/calc", open_pr=True)

    assert result.status == "PARTIAL"
    assert "timed out" in result.message and result.pushed
    assert result.rollback == [
        f"git -C {repo} push origin --delete fix/calc",
        f"git -C {repo} branch -D fix/calc",
    ]

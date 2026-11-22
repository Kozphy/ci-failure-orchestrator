from __future__ import annotations

import subprocess
from pathlib import Path

from ci_failure_orchestrator import patch_sandbox
from ci_failure_orchestrator.patch_sandbox import WorktreePatchVerifier


def _run(*argv: str, cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True, text=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git", "init", cwd=repo)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test", cwd=repo)
    (repo / "value.txt").write_text("one\n", encoding="utf-8")
    _run("git", "add", "value.txt", cwd=repo)
    _run("git", "commit", "-m", "initial", cwd=repo)
    return repo


def test_patch_verification_isolated_from_source_checkout(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = """diff --git a/value.txt b/value.txt
index 5626abf..f719efd 100644
--- a/value.txt
+++ b/value.txt
@@ -1 +1 @@
-one
+two
"""
    verifier = WorktreePatchVerifier(
        commands=(
            ("assert", ("python", "-c", "from pathlib import Path; assert Path('value.txt').read_text() == 'two\\n'")),
        )
    )
    result = verifier.verify(repo_path=repo, patch_text=patch)

    assert result.applied is True
    assert result.passed is True
    assert result.changed_files == ("value.txt",)
    assert result.steps[0].passed is True
    assert (repo / "value.txt").read_text(encoding="utf-8") == "one\n"


def test_invalid_patch_fails_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    verifier = WorktreePatchVerifier(commands=(("noop", ("python", "-c", "print('ok')")),))
    result = verifier.verify(repo_path=repo, patch_text="not a patch")
    assert result.applied is False
    assert result.passed is False
    assert result.reason == "patch_check_failed"


def test_verification_stops_on_first_failure(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = """diff --git a/value.txt b/value.txt
index 5626abf..f719efd 100644
--- a/value.txt
+++ b/value.txt
@@ -1 +1 @@
-one
+two
"""
    verifier = WorktreePatchVerifier(
        commands=(
            ("fail", ("python", "-c", "raise SystemExit(2)")),
            ("never", ("python", "-c", "raise SystemExit(0)")),
        )
    )
    result = verifier.verify(repo_path=repo, patch_text=patch)
    assert result.passed is False
    assert result.reason == "verification_failed"
    assert len(result.steps) == 1
    assert result.steps[0].returncode == 2


def test_container_isolation_fails_closed_when_docker_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _repo(tmp_path)
    patch = """diff --git a/value.txt b/value.txt
index 5626abf..f719efd 100644
--- a/value.txt
+++ b/value.txt
@@ -1 +1 @@
-one
+two
"""
    monkeypatch.setattr("ci_failure_orchestrator.patch_sandbox.shutil.which", lambda name: None)
    verifier = WorktreePatchVerifier(
        commands=(("assert", ("python", "-c", "print('ok')")),),
        container_image="python:3.12-slim",
    )
    result = verifier.verify(repo_path=repo, patch_text=patch)

    assert result.applied is True
    assert result.passed is False
    assert result.steps[0].returncode == 127
    assert "container_isolation_unavailable" in result.steps[0].stderr


def test_container_invocation_disables_network_and_limits_capabilities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(patch_sandbox.shutil, "which", lambda name: "docker")

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(patch_sandbox.subprocess, "run", fake_run)
    verifier = WorktreePatchVerifier(
        commands=(("noop", ("python", "-c", "pass")),),
        container_image="python:3.12-slim",
    )
    result = verifier._run_in_container(("python", "-c", "pass"), worktree=tmp_path, env={})

    assert result.returncode == 0
    run_args = calls[0]
    assert "--network" in run_args and run_args[run_args.index("--network") + 1] == "none"
    assert "--read-only" in run_args
    assert "--cap-drop" in run_args and run_args[run_args.index("--cap-drop") + 1] == "ALL"
    assert "--memory" in run_args and "--cpus" in run_args
    assert calls[1][1:3] == ["rm", "--force"]

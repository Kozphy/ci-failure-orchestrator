from __future__ import annotations

import subprocess
from pathlib import Path

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
    verifier = WorktreePatchVerifier(commands=(("assert", ("python", "-c", "from pathlib import Path; assert Path('value.txt').read_text() == 'two\\n'")),))
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
    verifier = WorktreePatchVerifier(commands=(
        ("fail", ("python", "-c", "raise SystemExit(2)")),
        ("never", ("python", "-c", "raise SystemExit(0)")),
    ))
    result = verifier.verify(repo_path=repo, patch_text=patch)
    assert result.passed is False
    assert result.reason == "verification_failed"
    assert len(result.steps) == 1
    assert result.steps[0].returncode == 2

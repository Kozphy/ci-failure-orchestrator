from pathlib import Path
import subprocess
import sys

from ci_failure_orchestrator.worktree import GitWorktreeWorkspace


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_git_worktree_isolated_from_source(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "ci@example.com")
    _git(source, "config", "user.name", "CI")
    (source / "value.txt").write_text("original\n", encoding="utf-8")
    _git(source, "add", "value.txt")
    _git(source, "commit", "-m", "base")

    with GitWorktreeWorkspace(source) as workspace:
        result = workspace.run([
            sys.executable,
            "-c",
            "from pathlib import Path; Path('value.txt').write_text('patched\\n')",
        ])
        assert result.returncode == 0
        assert "value.txt" in workspace.diff()

    assert (source / "value.txt").read_text(encoding="utf-8") == "original\n"

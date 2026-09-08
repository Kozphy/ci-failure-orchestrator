from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from .execution import ExecutionResult


class GitWorktreeWorkspace:
    """Creates a detached git worktree for repair execution and diff inspection.

    The source repository remains unchanged. The worktree is always removed on
    exit, making rollback a first-class operation.
    """

    def __init__(self, source: str | Path, ref: str = "HEAD"):
        self.source = Path(source).resolve()
        self.ref = ref
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> "GitWorktreeWorkspace":
        if not (self.source / ".git").exists():
            raise ValueError("git worktree execution requires a git repository")
        self._tmp = tempfile.TemporaryDirectory(prefix="ci-worktree-")
        self.path = Path(self._tmp.name) / "repo"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(self.path), self.ref],
            cwd=self.source,
            check=True,
            capture_output=True,
            text=True,
        )
        return self

    def run(self, argv: list[str], *, timeout_s: float = 120.0) -> ExecutionResult:
        if self.path is None:
            raise RuntimeError("workspace must be entered before execution")
        import time

        started = time.perf_counter()
        completed = subprocess.run(
            argv,
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            shell=False,
        )
        return ExecutionResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            workspace=str(self.path),
        )

    def diff(self) -> str:
        if self.path is None:
            raise RuntimeError("workspace must be entered before diff inspection")
        return subprocess.run(
            ["git", "diff", "--no-ext-diff"],
            cwd=self.path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def rollback(self) -> None:
        if self.path is not None and self.path.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(self.path)],
                cwd=self.source,
                check=False,
                capture_output=True,
                text=True,
            )
        if self._tmp is not None:
            self._tmp.cleanup()
        self._tmp = None
        self.path = None

    def __exit__(self, exc_type, exc, tb) -> None:
        self.rollback()

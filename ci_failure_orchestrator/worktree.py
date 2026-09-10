"""Git worktree workspace for isolated repair execution and diff inspection.

This module provides a detached git worktree workspace for repair execution,
ensuring the source repository remains unchanged. The worktree is always removed
on exit, making rollback a first-class operation.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from .execution import ExecutionResult


class GitWorktreeWorkspace:
    """Creates a detached git worktree for repair execution and diff inspection.

    This class provides a context manager that creates a detached git worktree
    for repair execution, ensuring the source repository remains unchanged. The
    worktree is always removed on exit, making rollback a first-class operation.

    Attributes:
        source: Path to the source repository (resolved absolute path).
        ref: Git reference to create the worktree from (default: "HEAD").
        _tmp: Temporary directory handle (None until context is entered).
        path: Path to the isolated workspace (None until context is entered).

    Audit Notes:
        - Worktree removal may fail if files are locked by other processes.
        - Detached worktree prevents accidental mutation of source repository.
        - Recovery: Manually clean up temporary directories if cleanup fails.
        - Evidence: All workspace operations include source and workspace paths for audit.

    Engineering Notes:
        - Trade-off: Detached worktree adds overhead but ensures complete isolation.
        - Design: TemporaryDirectory provides automatic cleanup on context exit.
        - Performance: Git worktree add is fast and provides efficient isolation.
    """

    def __init__(self, source: str | Path, ref: str = "HEAD"):
        """Initialize the git worktree workspace.

        Args:
            source: Path to the source repository.
            ref: Git reference to create the worktree from (default: "HEAD").
        """
        self.source = Path(source).resolve()
        self.ref = ref
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> "GitWorktreeWorkspace":
        """Enter the context and create the detached git worktree.

        Returns:
            The GitWorktreeWorkspace instance for use in the context.

        Raises:
            ValueError: If the source is not a git repository.

        Side Effects:
            - Creates a temporary directory in the system temp directory.
            - Creates a detached git worktree in the temporary directory.
        """
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
        """Execute a command in the isolated workspace.

        This method runs a command with explicit argv arrays (no shell=True) to
        prevent command injection attacks. The command executes in the isolated
        workspace directory.

        Args:
            argv: Command and arguments as a list of strings.
            timeout_s: Maximum execution time in seconds (default: 120.0).

        Returns:
            ExecutionResult with return code, stdout, stderr, elapsed time, and workspace path.

        Raises:
            RuntimeError: If the workspace has not been entered via __enter__.
            subprocess.TimeoutExpired: If the command execution exceeds the timeout.

        Side Effects:
            - Executes the command in the isolated workspace directory.
            - Captures stdout and stderr from the command.

        Safety Invariants:
            - shell=False prevents command injection attacks.
            - Timeout prevents runaway processes.
            - Isolated workspace prevents source repository mutation.
        """
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
        """Get the git diff from the isolated workspace.

        Returns:
            Git diff output as a string (unified diff format).

        Raises:
            RuntimeError: If the workspace has not been entered via __enter__.

        Side Effects:
            - Executes git diff command in the workspace.
        """
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
        """Rollback the workspace by removing the worktree and temporary directory.

        This method removes the git worktree and deletes the temporary directory,
        ensuring no resources are leaked and the source repository remains unchanged.

        Side Effects:
            - Removes the git worktree from the repository.
            - Deletes the temporary directory and all its contents.

        Idempotency:
            - Safe to call multiple times; subsequent calls are no-ops.
        """
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
        """Exit the context and rollback the workspace.

        Args:
            exc_type: Exception type if an exception occurred (unused).
            exc: Exception instance if an exception occurred (unused).
            tb: Traceback if an exception occurred (unused).

        Side Effects:
            - Calls rollback() to clean up the workspace.
        """
        self.rollback()

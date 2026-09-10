"""Isolated repair execution primitives.

This module provides isolated workspace execution for CI repair operations.
The executor deliberately separates proposal creation from execution and
verification. Commands are explicit argv arrays; shell=True is never used to
prevent command injection attacks. Workspaces are disposable copies of the
source repository to avoid mutation of the original codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Sequence


@dataclass(frozen=True)
class ExecutionResult:
    """Result from executing a command in an isolated workspace.

    Attributes:
        returncode: Process exit code (0 for success, non-zero for failure).
        stdout: Captured standard output as a string.
        stderr: Captured standard error as a string.
        elapsed_ms: Execution time in milliseconds.
        workspace: Path to the workspace where the command was executed.
    """

    returncode: int
    stdout: str
    stderr: str
    elapsed_ms: float
    workspace: str


class IsolatedWorkspace:
    """Creates a disposable copy of a repository tree for repair evaluation.

    This class provides a context manager that creates a temporary, isolated
    copy of a source repository for safe execution of repair proposals. The
    workspace is automatically cleaned up on exit, leaving the source repository
    untouched. Commands are executed with explicit argv arrays (no shell=True)
    to prevent command injection attacks.

    Attributes:
        source: Path to the source repository (resolved absolute path).
        _tmp: Temporary directory handle (None until context is entered).
        path: Path to the isolated workspace (None until context is entered).

    Audit Notes:
        - Isolated workspaces prevent accidental mutation of the source repository.
        - Shell execution is disabled (shell=False) to prevent command injection.
        - Workspace cleanup may fail if files are locked by other processes.
        - Recovery: Manually clean up temporary directories if cleanup fails.
        - Evidence: All execution results include workspace path and elapsed time for audit.

    Engineering Notes:
        - Trade-off: Full repository copy adds overhead but ensures complete isolation.
        - Design: Excludes .git, .venv, __pycache__, .pytest_cache to reduce copy time.
        - Performance: TemporaryDirectory provides automatic cleanup on context exit.
    """

    def __init__(self, source: str | Path):
        """Initialize the isolated workspace with a source repository path.

        Args:
            source: Path to the source repository to copy for isolation.
        """
        self.source = Path(source).resolve()
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> "IsolatedWorkspace":
        """Enter the context and create the isolated workspace.

        This method creates a temporary directory and copies the source repository
        into it, excluding build artifacts and VCS metadata.

        Returns:
            The IsolatedWorkspace instance for use in the context.

        Raises:
            ValueError: If the source repository does not exist or is not a directory.

        Side Effects:
            - Creates a temporary directory in the system temp directory.
            - Copies the source repository tree to the temporary directory.
            - Excludes .git, .venv, __pycache__, and .pytest_cache from the copy.
        """
        if not self.source.is_dir():
            raise ValueError(f"source repository does not exist: {self.source}")
        self._tmp = tempfile.TemporaryDirectory(prefix="ci-repair-")
        self.path = Path(self._tmp.name) / "repo"
        shutil.copytree(
            self.source,
            self.path,
            ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"),
        )
        return self

    def run(self, argv: Sequence[str], *, timeout_s: float = 120.0) -> ExecutionResult:
        """Execute a command in the isolated workspace.

        This method runs a command with explicit argv arrays (no shell=True) to
        prevent command injection attacks. The command executes in the isolated
        workspace directory, ensuring the source repository remains untouched.

        Args:
            argv: Command and arguments as a sequence of strings.
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
            list(argv),
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            shell=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        return ExecutionResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            elapsed_ms=elapsed_ms,
            workspace=str(self.path),
        )

    def rollback(self) -> None:
        """Discard the disposable workspace; source repository remains untouched.

        This method cleans up the temporary directory and removes the isolated
        workspace copy. The source repository is never modified.

        Side Effects:
            - Deletes the temporary directory and all its contents.
            - Sets _tmp and path to None to indicate workspace is closed.

        Idempotency:
            - Safe to call multiple times; subsequent calls are no-ops.
        """
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
            self.path = None

    def __exit__(self, exc_type, exc, tb) -> None:
        """Exit the context and clean up the isolated workspace.

        Args:
            exc_type: Exception type if an exception occurred (unused).
            exc: Exception instance if an exception occurred (unused).
            tb: Traceback if an exception occurred (unused).

        Side Effects:
            - Calls rollback() to clean up the temporary directory.
        """
        self.rollback()

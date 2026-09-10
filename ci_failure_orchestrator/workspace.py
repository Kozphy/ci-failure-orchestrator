"""Isolated git workspace management for repair execution.

This module provides isolated git workspace creation using git worktree,
ensuring that repair proposals are executed in isolated environments without
mutating the source repository. Workspaces support patch application and rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile


@dataclass(frozen=True)
class WorkspaceResult:
    """Result from creating an isolated git workspace.

    Attributes:
        path: Path to the isolated workspace directory.
        branch: Branch name for the workspace.
    """

    path: Path
    branch: str


class IsolatedGitWorkspace:
    """Create and tear down an isolated git worktree for one repair candidate.

    This class provides isolated workspace management using git worktree,
    ensuring that repair proposals are executed in isolated environments without
    mutating the source repository. Workspaces support patch application and
    rollback, and are automatically cleaned up on close.

    Attributes:
        repo_path: Path to the source repository (resolved absolute path).
        _tmp: Temporary directory handle (None until workspace is created).
        result: WorkspaceResult with path and branch (None until workspace is created).

    Audit Notes:
        - Failed worktree creation is cleaned up to prevent resource leaks.
        - Patch application failures leave the workspace in a clean state via rollback.
        - Worktree removal may fail if files are locked by other processes.
        - Recovery: Manually clean up temporary directories if cleanup fails.
        - Evidence: All workspace operations include paths and branch names for audit.

    Engineering Notes:
        - Trade-off: Git worktree adds overhead but ensures complete isolation.
        - Design: Branch-specific worktrees allow concurrent repair evaluation.
        - Performance: TemporaryDirectory provides automatic cleanup on close.
    """

    def __init__(self, repo_path: str | Path):
        """Initialize the isolated git workspace manager.

        Args:
            repo_path: Path to the source repository.
        """
        self.repo_path = Path(repo_path).resolve()
        self._tmp: str | None = None
        self.result: WorkspaceResult | None = None

    def create(self, base_ref: str, branch: str) -> WorkspaceResult:
        """Create an isolated git worktree from a base reference.

        This method creates a new git worktree using the specified base reference
        and branch name, providing an isolated environment for repair execution.

        Args:
            base_ref: Git reference to create the worktree from (e.g., "HEAD", commit SHA).
            branch: Branch name for the new worktree.

        Returns:
            WorkspaceResult with path to the workspace and branch name.

        Raises:
            RuntimeError: If workspace is already created or worktree creation fails.

        Side Effects:
            - Creates a temporary directory in the system temp directory.
            - Creates a git worktree in the temporary directory.
            - Cleans up temporary directory if worktree creation fails.

        Failure Modes:
            - Git worktree add may fail if base_ref is invalid.
            - Temporary directory creation may fail if disk is full.
        """
        if self.result is not None:
            raise RuntimeError("workspace already created")
        self._tmp = tempfile.mkdtemp(prefix="ci-repair-")
        target = Path(self._tmp) / "worktree"
        proc = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(target), base_ref],
            cwd=self.repo_path,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None
            raise RuntimeError(f"failed to create worktree: {proc.stderr.strip()}")
        self.result = WorkspaceResult(target, branch)
        return self.result

    def apply_patch(self, patch: str) -> None:
        """Apply a patch to the isolated workspace.

        This method applies a unified diff patch to the workspace using git apply,
        ensuring the repair proposal is applied to the isolated environment.

        Args:
            patch: Unified diff patch content as a string.

        Raises:
            RuntimeError: If workspace is not created or patch application fails.

        Side Effects:
            - Applies the patch to the workspace files.
            - Git apply may modify files in the workspace.

        Failure Modes:
            - Patch application may fail if patch is malformed or conflicts with workspace state.
        """
        if self.result is None:
            raise RuntimeError("workspace not created")
        proc = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=self.result.path,
            input=patch,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"patch apply failed: {proc.stderr.strip()}")

    def rollback(self) -> None:
        """Rollback the workspace to a clean state.

        This method resets the workspace to HEAD and removes untracked files,
        reverting any changes made during repair execution.

        Side Effects:
            - Resets the workspace to HEAD (discards all changes).
            - Removes untracked files from the workspace.

        Idempotency:
            - Safe to call multiple times; subsequent calls are no-ops if workspace not created.
        """
        if self.result is None:
            return
        subprocess.run(
            ["git", "reset", "--hard", "HEAD"],
            cwd=self.result.path,
            text=True,
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["git", "clean", "-fd"],
            cwd=self.result.path,
            text=True,
            capture_output=True,
            check=False,
        )

    def close(self) -> None:
        """Close and clean up the isolated workspace.

        This method removes the git worktree and deletes the temporary directory,
        ensuring no resources are leaked.

        Side Effects:
            - Removes the git worktree from the repository.
            - Deletes the temporary directory and all its contents.

        Idempotency:
            - Safe to call multiple times; subsequent calls are no-ops.
        """
        if self.result is not None:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(self.result.path)],
                cwd=self.repo_path,
                text=True,
                capture_output=True,
                check=False,
            )
            self.result = None
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None

    def __enter__(self) -> "IsolatedGitWorkspace":
        """Enter the context manager.

        Returns:
            The IsolatedGitWorkspace instance for use in the context.
        """
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Exit the context and clean up the workspace.

        Args:
            exc_type: Exception type if an exception occurred (unused).
            exc: Exception instance if an exception occurred (unused).
            tb: Traceback if an exception occurred (unused).

        Side Effects:
            - Calls close() to clean up the workspace.
        """
        self.close()

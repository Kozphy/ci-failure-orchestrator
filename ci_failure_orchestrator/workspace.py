from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile


@dataclass(frozen=True)
class WorkspaceResult:
    path: Path
    branch: str


class IsolatedGitWorkspace:
    """Create and tear down an isolated git worktree for one repair candidate."""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self._tmp: str | None = None
        self.result: WorkspaceResult | None = None

    def create(self, base_ref: str, branch: str) -> WorkspaceResult:
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
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

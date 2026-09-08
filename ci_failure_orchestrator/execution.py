"""Isolated repair execution primitives.

The executor deliberately separates proposal creation from execution and
verification. Commands are explicit argv arrays; shell=True is never used.
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
    returncode: int
    stdout: str
    stderr: str
    elapsed_ms: float
    workspace: str


class IsolatedWorkspace:
    """Creates a disposable copy of a repository tree for repair evaluation."""

    def __init__(self, source: str | Path):
        self.source = Path(source).resolve()
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> "IsolatedWorkspace":
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
        """Discard the disposable workspace; source repository remains untouched."""
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
            self.path = None

    def __exit__(self, exc_type, exc, tb) -> None:
        self.rollback()

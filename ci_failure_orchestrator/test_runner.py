from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from time import perf_counter
from typing import Iterable


@dataclass(frozen=True)
class TestRunResult:
    command: tuple[str, ...]
    returncode: int
    passed: bool
    latency_ms: int
    stdout: str
    stderr: str


class TargetedTestRunner:
    """Execute targeted tests first, with optional full-suite regression."""

    def __init__(self, python_executable: str = "python"):
        self.python_executable = python_executable

    def run_pytest(
        self,
        workspace: str | Path,
        tests: Iterable[str],
        *,
        timeout_seconds: int = 300,
    ) -> TestRunResult:
        selected = tuple(tests)
        command = (self.python_executable, "-m", "pytest", *selected)
        start = perf_counter()
        try:
            proc = subprocess.run(
                command,
                cwd=Path(workspace),
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            latency_ms = int((perf_counter() - start) * 1000)
            return TestRunResult(
                command,
                124,
                False,
                latency_ms,
                exc.stdout or "",
                exc.stderr or "test execution timed out",
            )
        latency_ms = int((perf_counter() - start) * 1000)
        return TestRunResult(
            command,
            proc.returncode,
            proc.returncode == 0,
            latency_ms,
            proc.stdout,
            proc.stderr,
        )

    def run_full_suite(
        self,
        workspace: str | Path,
        *,
        timeout_seconds: int = 900,
    ) -> TestRunResult:
        return self.run_pytest(workspace, (), timeout_seconds=timeout_seconds)

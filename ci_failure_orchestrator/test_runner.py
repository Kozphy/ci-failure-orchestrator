"""Test execution for CI repair verification.

This module provides test execution for CI repair verification, including
targeted test execution for fast feedback and full regression suite execution
for comprehensive verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from time import perf_counter
from typing import Iterable


@dataclass(frozen=True)
class TestRunResult:
    """Result from test execution.

    Attributes:
        command: Command tuple that was executed.
        returncode: Process exit code (0 for success, non-zero for failure).
        passed: Whether all tests passed (returncode == 0).
        latency_ms: Execution time in milliseconds.
        stdout: Captured standard output as a string.
        stderr: Captured standard error as a string.
    """

    command: tuple[str, ...]
    returncode: int
    passed: bool
    latency_ms: int
    stdout: str
    stderr: str


class TargetedTestRunner:
    """Execute targeted tests first, with optional full-suite regression.

    This runner provides fast feedback through targeted test execution,
    with support for full regression suite execution to ensure comprehensive
    verification of repair proposals.

    Attributes:
        python_executable: Python executable to use for pytest (default: "python").

    Audit Notes:
        - Test execution may timeout if tests hang or are slow.
        - Failed tests indicate regression or invalid repair.
        - Recovery: Review test output to diagnose failure cause.
        - Evidence: All test results include command, latency, and output for audit.

    Engineering Notes:
        - Trade-off: Targeted tests provide fast feedback but may miss regressions.
        - Design: Full suite required for release authorization (targeted tests alone insufficient).
        - Performance: Timeout prevents runaway test execution.
    """

    def __init__(self, python_executable: str = "python"):
        """Initialize the targeted test runner.

        Args:
            python_executable: Python executable to use for pytest (default: "python").
        """
        self.python_executable = python_executable

    def run_pytest(
        self,
        workspace: str | Path,
        tests: Iterable[str],
        *,
        timeout_seconds: int = 300,
    ) -> TestRunResult:
        """Run pytest on specified tests in the workspace.

        This method executes pytest on the specified tests with a timeout to
        prevent runaway test execution.

        Args:
            workspace: Path to the workspace containing tests.
            tests: Iterable of test paths or names to execute.
            timeout_seconds: Maximum execution time in seconds (default: 300).

        Returns:
            TestRunResult with command, return code, pass status, latency, and output.

        Side Effects:
            - Executes pytest in the workspace directory.
            - Captures stdout and stderr from pytest.

        Failure Modes:
            - Test execution may timeout if tests hang or are slow.
            - Tests may fail if the repair introduced regressions.
        """
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
        """Run the full test suite in the workspace.

        This method executes pytest without specifying specific tests, running
        the full test suite for comprehensive regression verification.

        Args:
            workspace: Path to the workspace containing tests.
            timeout_seconds: Maximum execution time in seconds (default: 900).

        Returns:
            TestRunResult with command, return code, pass status, latency, and output.

        Side Effects:
            - Executes pytest in the workspace directory.
            - Captures stdout and stderr from pytest.

        Safety Invariants:
            - Full suite required for release authorization (targeted tests alone insufficient).
            - Timeout prevents runaway test execution.
        """
        return self.run_pytest(workspace, (), timeout_seconds=timeout_seconds)

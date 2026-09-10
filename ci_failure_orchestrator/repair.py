"""Deterministic repair execution for benchmark fixtures.

This module provides a deterministic repair planner and sandbox executor for
benchmark fixtures. It intentionally avoids arbitrary shell/code generation to ensure
reproducible benchmark results. Repairs are limited to safe strategies:
replace_text, append_line, and remove_line.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Callable


@dataclass(frozen=True)
class RepairPlan:
    """Deterministic repair plan for a benchmark fixture.

    Attributes:
        strategy: Repair strategy (replace_text, append_line, or remove_line).
        target_path: Path to the file to repair.
        description: Human-readable description of the repair.
        candidate_index: Index of the repair candidate in the case (default: 0).
    """

    strategy: str
    target_path: str
    description: str
    candidate_index: int = 0


@dataclass(frozen=True)
class RepairAttempt:
    """Result from a repair execution attempt.

    Attributes:
        strategy: Repair strategy that was executed.
        success: Whether the repair succeeded (tests passed).
        duration_seconds: Execution time in seconds.
        regression_detected: Whether regression was detected.
        stdout: Captured standard output from verification.
        stderr: Captured standard error from verification.
    """

    strategy: str
    success: bool
    duration_seconds: float
    regression_detected: bool
    stdout: str
    stderr: str

    def to_dict(self) -> dict:
        """Convert the repair attempt to a dictionary representation.

        Returns:
            Dictionary containing all attempt fields.
        """
        return asdict(self)


SAFE_STRATEGIES = {
    "replace_text",
    "append_line",
    "remove_line",
}


class RepairPlanner:
    """Deterministic repair planner for benchmark fixtures.

    This planner generates repair plans from fixture metadata, ensuring
    reproducible benchmark results by avoiding arbitrary shell/code generation.
    Only safe strategies (replace_text, append_line, remove_line) are allowed.

    Audit Notes:
        - Unsafe strategies could execute arbitrary code or cause file corruption.
        - Strategy validation prevents accidental use of unsafe strategies.
        - Recovery: Review strategy whitelist if repairs are too restrictive.
        - Evidence: All plans include strategy and target path for audit.

    Engineering Notes:
        - Trade-off: Limited strategies ensure safety but restrict repair capabilities.
        - Design: Deterministic plans from fixture metadata ensure reproducibility.
        - Performance: Simple strategy filtering is fast and deterministic.
    """

    def plan(self, case: dict) -> list[RepairPlan]:
        """Generate repair plans from benchmark fixture metadata.

        This method generates repair plans from fixture case data, filtering
        to only include safe strategies and matching candidate metadata.

        Args:
            case: Benchmark fixture case dictionary with repair_candidates array.

        Returns:
            List of RepairPlan objects with strategy, target path, and description.

        Plan Generation:
            - Iterates over repair_candidates in the case.
            - Filters to only include SAFE_STRATEGIES (replace_text, append_line, remove_line).
            - Validates plan matches candidate metadata (strategy and target_path).

        Side Effects:
            - None (pure plan generation).

        Failure Modes:
            - Invalid candidate index may raise IndexError.
            - Mismatched plan and candidate metadata may raise ValueError.
        """
        plans = []
        for index, candidate in enumerate(case.get("repair_candidates", [])):
            strategy = candidate.get("strategy", "")
            if strategy not in SAFE_STRATEGIES:
                continue
            plans.append(
                RepairPlan(
                    strategy=strategy,
                    target_path=candidate["target_path"],
                    description=candidate.get("description", strategy),
                    candidate_index=index,
                )
            )
        return plans


class SandboxRepairExecutor:
    """Runs deterministic file repairs inside a disposable directory.

    This executor creates a temporary sandbox directory, copies the fixture
    directory, applies the repair plan, and verifies the result with a
    provided verification function. The sandbox is automatically cleaned up.

    Attributes:
        verify: Verification function that takes a Path and returns (success, regression, stdout, stderr).

    Audit Notes:
        - Sandbox isolation prevents fixture corruption from repairs.
        - Verification detects regressions and test failures.
        - Failed repairs leave the fixture unchanged (sandbox is disposable).
        - Recovery: Review verification function if repairs are incorrectly rejected.

    Engineering Notes:
        - Trade-off: Sandbox copying adds overhead but ensures fixture isolation.
        - Design: Disposable sandbox prevents fixture contamination.
        - Performance: shutil.copytree is fast for small fixtures.
    """

    def __init__(self, verify: Callable[[Path], tuple[bool, bool, str, str]]):
        """Initialize the sandbox repair executor.

        Args:
            verify: Verification function that takes a Path and returns (success, regression, stdout, stderr).
        """
        self.verify = verify

    def run(self, fixture_dir: Path, case: dict, plan: RepairPlan) -> RepairAttempt:
        """Execute a repair plan in a sandboxed environment.

        This method creates a temporary sandbox, copies the fixture directory,
        applies the repair plan, runs verification, and returns the result.

        Args:
            fixture_dir: Path to the fixture directory to copy.
            case: Benchmark fixture case dictionary with repair_candidates.
            plan: RepairPlan to execute.

        Returns:
            RepairAttempt with strategy, success, duration, regression status, and output.

        Raises:
            IndexError: If candidate_index is out of range.
            ValueError: If plan no longer matches candidate metadata.
            FileNotFoundError: If target file does not exist in the sandbox.

        Side Effects:
            - Creates a temporary directory and copies the fixture.
            - Modifies files in the sandbox according to the repair plan.
            - Runs verification tests in the sandbox.
            - Deletes the temporary directory after execution.

        Safety Invariants:
            - Sandbox isolation prevents fixture corruption.
            - Only safe strategies are executed (validated by planner).
            - Target file must exist in the sandbox.
        """
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="ci-repair-") as tmp:
            sandbox = Path(tmp) / "repo"
            shutil.copytree(fixture_dir, sandbox)
            target = sandbox / plan.target_path
            candidates = case.get("repair_candidates", [])
            if plan.candidate_index >= len(candidates):
                raise IndexError(f"repair candidate index out of range: {plan.candidate_index}")
            candidate = candidates[plan.candidate_index]
            if candidate.get("strategy") != plan.strategy or candidate.get("target_path") != plan.target_path:
                raise ValueError("repair plan no longer matches its candidate payload")
            self._apply(target, candidate)
            success, regression, stdout, stderr = self.verify(sandbox)
        duration = time.perf_counter() - started
        return RepairAttempt(
            strategy=plan.strategy,
            success=success,
            duration_seconds=round(duration, 6),
            regression_detected=regression,
            stdout=stdout,
            stderr=stderr,
        )

    def _apply(self, target: Path, candidate: dict) -> None:
        """Apply a repair to the target file according to the strategy.

        This method applies the repair using the specified strategy (replace_text,
        append_line, or remove_line) with the provided candidate metadata.

        Args:
            target: Path to the target file to repair.
            candidate: Candidate dictionary with strategy and repair parameters.

        Raises:
            FileNotFoundError: If target file does not exist.
            ValueError: If repair token not found (replace_text) or strategy is unsafe.

        Side Effects:
            - Modifies the target file according to the repair strategy.

        Repair Strategies:
            - replace_text: Replace old string with new string (single occurrence).
            - append_line: Append a line to the end of the file.
            - remove_line: Remove a line matching the needle.
        """
        if not target.exists():
            raise FileNotFoundError(target)
        text = target.read_text(encoding="utf-8")
        strategy = candidate["strategy"]
        if strategy == "replace_text":
            old = candidate["old"]
            new = candidate["new"]
            if old not in text:
                raise ValueError(f"repair token not found in {target}")
            target.write_text(text.replace(old, new, 1), encoding="utf-8")
        elif strategy == "append_line":
            target.write_text(text + candidate["line"] + "\n", encoding="utf-8")
        elif strategy == "remove_line":
            needle = candidate["line"]
            lines = [line for line in text.splitlines() if line != needle]
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            raise ValueError(f"unsafe repair strategy: {strategy}")


def pytest_verifier(command: tuple[str, ...] = ("python", "-m", "pytest", "-q")):
    """Create a pytest verification function for repair validation.

    This function returns a verification function that runs pytest in a repository
    and returns (success, regression, stdout, stderr). The verification function
    treats test failure as regression for safety.

    Args:
        command: Command tuple to run pytest (default: ("python", "-m", "pytest", "-q")).

    Returns:
        Verification function that takes a Path and returns (success, regression, stdout, stderr).

    Verification Logic:
        - Success: pytest exit code == 0.
        - Regression: test failure (exit code != 0).
        - Timeout: 30 seconds to prevent runaway tests.

    Side Effects:
        - Executes pytest in the repository directory.

    Audit Notes:
        - Verification timeout prevents runaway test execution.
        - Test failure is treated as regression for safety.
        - Recovery: Adjust timeout if tests legitimately require more time.
        - Evidence: All verification results include stdout and stderr for audit.

    Engineering Notes:
        - Trade-off: Fixed timeout may fail slow but valid tests.
        - Design: Test failure treated as regression for fail-closed safety.
        - Performance: subprocess.run with timeout prevents runaway processes.
    """
    def verify(repo: Path) -> tuple[bool, bool, str, str]:
        completed = subprocess.run(
            command,
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        passed = completed.returncode == 0
        return passed, not passed, completed.stdout, completed.stderr

    return verify

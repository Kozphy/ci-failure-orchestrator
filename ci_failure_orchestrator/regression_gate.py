"""Mandatory full-regression verification before release.

This module enforces the safety rule that targeted tests can fail fast but can never
authorize release. A candidate repair must pass the configured full-suite command
before the policy layer may consider it releasable. This prevents partial test
coverage from authorizing potentially dangerous changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .execution import ExecutionResult


@dataclass(frozen=True)
class RegressionGateResult:
    """Result from regression gate verification.

    Attributes:
        targeted_passed: Whether the targeted test command passed (if executed).
        full_suite_passed: Whether the full regression suite passed.
        releasable: Whether the repair may be released (requires both to pass).
        targeted: Execution result from targeted tests (None if not executed).
        full_suite: Execution result from full regression suite.
    """

    targeted_passed: bool
    full_suite_passed: bool
    releasable: bool
    targeted: ExecutionResult | None
    full_suite: ExecutionResult


class MandatoryRegressionGate:
    """Enforces mandatory full-regression verification before release authorization.

    This gate implements the critical safety rule that targeted tests can fail fast
    but can never authorize release. Only the full regression suite can authorize
    release, ensuring comprehensive test coverage before potentially dangerous changes
    are promoted.

    Attributes:
        full_suite_command: Command sequence for the full regression suite (required).

    Raises:
        ValueError: If full_suite_command is empty.

    Audit Notes:
        - Failed targeted tests reject the candidate without running full suite (saves CI budget).
        - Only full suite passage can authorize release (targeted tests alone are insufficient).
        - Bypassing this gate could release untested or dangerous changes.
        - Recovery: Review test failures and fix regressions before attempting release.
        - Evidence: All gate results include targeted and full suite execution details.

    Engineering Notes:
        - Trade-off: Running full suite on every targeted failure wastes CI budget.
        - Design: Skip full suite when targeted tests fail (early rejection).
        - Performance: Targeted tests provide fast feedback; full suite provides safety.
    """

    def __init__(self, full_suite_command: Sequence[str]):
        """Initialize the mandatory regression gate.

        Args:
            full_suite_command: Command sequence for the full regression suite.

        Raises:
            ValueError: If full_suite_command is empty.
        """
        if not full_suite_command:
            raise ValueError("full_suite_command must not be empty")
        self.full_suite_command = tuple(full_suite_command)

    def verify(self, workspace, *, targeted_command: Sequence[str] | None = None) -> RegressionGateResult:
        """Verify a repair candidate against the regression gate.

        This method runs targeted tests (if provided) for fast feedback, then runs
        the full regression suite if targeted tests pass. A repair is only releasable
        if both targeted tests (if executed) and the full suite pass.

        Args:
            workspace: Workspace execution context with run() method.
            targeted_command: Optional command sequence for targeted tests.

        Returns:
            RegressionGateResult with pass/fail status and execution details.

        Verification Logic:
            - If targeted_command provided: Run targeted tests first.
            - If targeted tests fail: Reject immediately (skip full suite to save CI budget).
            - If targeted tests pass or not provided: Run full regression suite.
            - Release authorized only if full suite passes.

        Side Effects:
            - Executes commands in the workspace (may have side effects).
            - May skip full suite execution if targeted tests fail (budget optimization).
        """
        targeted_result = None
        targeted_passed = True
        if targeted_command:
            targeted_result = workspace.run(targeted_command)
            targeted_passed = targeted_result.returncode == 0
            if not targeted_passed:
                # Still run the full suite only when explicitly useful would waste CI budget;
                # a failed targeted check is already sufficient to reject the candidate.
                return RegressionGateResult(
                    targeted_passed=False,
                    full_suite_passed=False,
                    releasable=False,
                    targeted=targeted_result,
                    full_suite=targeted_result,
                )

        full_suite = workspace.run(self.full_suite_command)
        full_suite_passed = full_suite.returncode == 0
        return RegressionGateResult(
            targeted_passed=targeted_passed,
            full_suite_passed=full_suite_passed,
            releasable=targeted_passed and full_suite_passed,
            targeted=targeted_result,
            full_suite=full_suite,
        )

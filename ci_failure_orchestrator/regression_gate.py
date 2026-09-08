"""Mandatory full-regression verification before release.

Targeted tests can fail fast, but they can never authorize release. A candidate
repair must pass the configured full-suite command before the policy layer may
consider it releasable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .execution import ExecutionResult


@dataclass(frozen=True)
class RegressionGateResult:
    targeted_passed: bool
    full_suite_passed: bool
    releasable: bool
    targeted: ExecutionResult | None
    full_suite: ExecutionResult


class MandatoryRegressionGate:
    def __init__(self, full_suite_command: Sequence[str]):
        if not full_suite_command:
            raise ValueError("full_suite_command must not be empty")
        self.full_suite_command = tuple(full_suite_command)

    def verify(self, workspace, *, targeted_command: Sequence[str] | None = None) -> RegressionGateResult:
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

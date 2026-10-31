"""Dependency-light adversarial checks against the canonical CI repair core."""

import unittest

from ci_failure_orchestrator.foundation.evaluator import LocalEvaluator
from ci_failure_orchestrator.foundation.models import (
    CheckStatus, EvaluationCheck, EvaluationResult, RepairProposal, RunStatus,
    SandboxResult, ToolResult,
)
from ci_failure_orchestrator.foundation.remediation import (
    GateStatus, RemediationState, VerificationResult, decide_remediation, is_verified_fix,
)
from ci_failure_orchestrator.foundation.retry import (
    AttemptRecord, FailureDisposition, RetryBudget, RetryDecisionEngine, RetryReason,
)
from ci_failure_orchestrator.foundation.state_machine import FoundationStateMachine, InvalidStateTransition
from ci_failure_orchestrator.service.patches import patch_violation


def complete(**changes):
    """Return explicitly collected, passing synthetic evidence."""
    values = dict(
        repair_proposed=True, patch_applied=True, original_failure_reproduced=True,
        original_failure_resolved=True, targeted_test_passed=True,
        test_count_decreased=False, skipped_tests_increased=False,
        policy_outcome="APPROVE", risk_level="LOW", real_ci_passed=True,
    )
    values.update({g: GateStatus.PASSED for g in (
        "affected_tests", "regression_suite", "coverage", "lint", "typecheck",
        "security", "build", "behavioral_invariants",
    )})
    values.update(changes)
    return VerificationResult(**values)


class AssuranceRegressions(unittest.TestCase):
    def test_positive_control_is_verified(self):
        self.assertTrue(is_verified_fix(complete()))
        self.assertEqual(decide_remediation(complete()).state, RemediationState.VERIFIED_FIXED)

    def test_unknown_skip_comparison_never_verifies(self):
        result = complete(skipped_tests_increased=None)
        self.assertFalse(is_verified_fix(result))
        decision = decide_remediation(result)
        self.assertEqual(decision.state, RemediationState.CI_GREEN_BUT_UNVERIFIED)
        self.assertIn("skipped_test_comparison", decision.missing_evidence)

    def test_human_approval_cannot_override_policy_rejection(self):
        result = complete(policy_outcome="REJECT", human_approved=True)
        self.assertFalse(is_verified_fix(result))
        self.assertEqual(decide_remediation(result).state, RemediationState.POLICY_REJECTED)

    def test_forbidden_codes_and_flag_cannot_disagree_into_success(self):
        result = complete(forbidden_diff_codes=("TEST_CASE_REMOVED",), forbidden_diff_detected=False)
        self.assertFalse(is_verified_fix(result))
        self.assertEqual(decide_remediation(result).state, RemediationState.POLICY_REJECTED)

    def test_green_ci_does_not_replace_missing_baseline(self):
        self.assertFalse(is_verified_fix(complete(original_failure_reproduced=None)))

    def test_any_missing_gate_blocks_verified_outcome(self):
        for gate in ("regression_suite", "coverage", "lint", "typecheck", "security", "build"):
            with self.subTest(gate=gate):
                self.assertFalse(is_verified_fix(complete(**{gate: GateStatus.NOT_RUN})))

    def test_evaluator_fails_on_each_explicit_failed_check(self):
        proposal = RepairProposal("p", "r", ("src/calc.py",), "patch", "fix", "correct", ("target",))
        target = ToolResult("test_runner", True)
        for failed in (
            ToolResult("lint", False, exit_code=1),
            ToolResult("typecheck", False, exit_code=1),
            ToolResult("test_runner", False, exit_code=1, metadata={"step": "relevant_tests"}),
        ):
            with self.subTest(tool=failed.tool_name, metadata=failed.metadata):
                sandbox = SandboxResult("r", "p", True, True, (target, failed), ("src/calc.py",))
                evaluation = LocalEvaluator().evaluate(proposal=proposal, sandbox=sandbox)
                self.assertTrue(any(c.status is CheckStatus.FAILED for c in evaluation.checks))
                self.assertFalse(evaluation.passed)

    def test_timeout_and_missing_target_fail_closed(self):
        proposal = RepairProposal("p", "r", ("src/a.py",), "patch", "fix", "correct", ("target",))
        for results, timeout in (((), False), ((ToolResult("test_runner", True),), True)):
            with self.subTest(timeout=timeout):
                sandbox = SandboxResult("r", "p", False, True, results, ("src/a.py",), timeout=timeout)
                self.assertFalse(LocalEvaluator().evaluate(proposal=proposal, sandbox=sandbox).passed)

    def test_retry_budget_exhaustion_stops(self):
        evaluation = EvaluationResult("r", False, True, False, True, False,
                                      (EvaluationCheck("target", CheckStatus.FAILED),), ())
        attempt = AttemptRecord(1, "fix", "p", "fingerprint", "failure", False, True, False,
                                1, None, FailureDisposition.RECOVERABLE)
        decision = RetryDecisionEngine().decide(RetryBudget(max_attempts=1), [attempt], evaluation)
        self.assertFalse(decision.should_retry)
        self.assertEqual(decision.reason, RetryReason.MAX_ATTEMPTS_EXHAUSTED)
        self.assertEqual(decision.budget_remaining, 0)

    def test_forbidden_patch_paths_and_symlinks(self):
        for patch in (
            "diff --git a/../outside b/../outside\n--- a/../outside\n+++ b/../outside\n",
            "diff --git a/.git/config b/.git/config\n--- a/.git/config\n+++ b/.git/config\n",
            "diff --git a/link b/link\nnew file mode 120000\n",
        ):
            with self.subTest(patch=patch):
                self.assertIsNotNone(patch_violation(patch))

    def test_terminal_state_cannot_resume_automation(self):
        machine = FoundationStateMachine(RunStatus.APPROVED)
        with self.assertRaises(InvalidStateTransition):
            machine.transition(RunStatus.EXECUTING, "unapproved restart")
        self.assertEqual(machine.status, RunStatus.APPROVED)
        self.assertEqual(machine.history, [])


if __name__ == "__main__":
    unittest.main()

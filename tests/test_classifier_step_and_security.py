"""Foundation classifier: security scans escalate; linters quoting source are not dependency failures.

Each fix has a guard case for the direction that would make the policy gate less safe.
"""

from __future__ import annotations

import pytest

from ci_failure_orchestrator.foundation.classifier import FailureClassifier
from ci_failure_orchestrator.foundation.models import EvaluationResult, FailureEvent, RepairProposal
from ci_failure_orchestrator.foundation.policy import (
    RULE_FAILURE_CATEGORY,
    PolicyOutcome,
    StaticPolicyEngine,
    build_policy_context,
)


def _event(job: str, step: str, message: str, log: str, workflow: str = "ci") -> FailureEvent:
    return FailureEvent(
        event_id="e",
        run_id="r",
        source="github_actions",
        workflow=workflow,
        job=job,
        failed_step=step,
        message=message,
        log_excerpt=log,
    )


def _category(*args: str) -> str:
    return FailureClassifier().classify(_event(*args)).category


RUFF_LOG = (
    "I001 [*] Import block is un-sorted or un-formatted\n"
    "18 | from .provenance import DependencyProvenanceEvaluator\n"
    "Found 1 error.\n"
)


def test_lint_step_quoting_a_dependency_identifier_is_a_lint_failure():
    classification = FailureClassifier().classify(
        _event("test", "Trust control-plane lint", "Found 1 error.", RUFF_LOG)
    )

    assert classification.category == "lint_failure"
    assert "log=DEPENDENCY_ERROR:quoted_source" in classification.evidence


def test_type_check_step_quoting_source_is_a_type_failure():
    log = "src/deps.py:4: error: Incompatible types\n    resolver = DependencyResolver()\n"
    assert _category("checks", "Run mypy", "Found 1 error in 1 file", log) == "type_failure"


@pytest.mark.parametrize(
    ("job", "step", "message", "log"),
    [
        # A "lint" job failing in its install step: the job name must not override.
        (
            "lint",
            "Install dependencies",
            "ERROR: Cannot install flake8==7.0 and pyflakes==2.0 because these package versions have conflicts.",
            "ERROR: ResolutionImpossible: see https://pip.pypa.io/dependency-resolution/",
        ),
        # pytest collection error on a missing module: test steps never override.
        ("test", "pytest", "Interrupted: 1 error during collection", "ModuleNotFoundError: No module named 'requests'"),
        # The environment signal is in the message itself.
        ("lint", "Run ruff", "ModuleNotFoundError: No module named 'ruff'", "No module named 'ruff'"),
        # No message: the log is all there is, so it decides.
        ("lint", "Run ruff", "", "No module named 'ruff'"),
    ],
)
def test_real_environment_failures_stay_dependency_failures(job, step, message, log):
    assert _category(job, step, message, log) == "dependency_failure"


@pytest.mark.parametrize(
    ("job", "step", "message", "log", "workflow"),
    [
        ("Gitleaks", "Run gitleaks/gitleaks-action@v3", "Leaks detected, see job summary for details", "", "security"),
        ("scan", "Run trivy", "Process completed with exit code 1.", "", "ci"),
        ("analyze", "Perform CodeQL Analysis", "exit code 1", "", "codeql"),
        ("audit", "pip-audit", "Found 2 known vulnerabilities", "2 vulnerabilities found in 1 package", "ci"),
        # Previously mapped to configuration_failure, which policy did not escalate.
        ("deploy", "check", "security scan failed: secret detected in config", "", "ci"),
        # A security tool lint-checking itself still counts as security: it outranks the lint step.
        ("lint", "Run ruff and bandit", "Found 1 error.", RUFF_LOG, "ci"),
    ],
)
def test_security_scans_get_their_own_category(job, step, message, log, workflow):
    assert _category(job, step, message, log, workflow) == "security_scan_failure"


def test_scanner_success_lines_are_not_security_findings():
    log = "INF no leaks found\nNo known vulnerabilities found\nFAILED tests/test_a.py::test_x - AssertionError\n"
    assert _category("test", "pytest", "AssertionError", log) == "test_failure"


RAW_PYTEST_Q_LOG = (
    "..F.                                                                     [100%]\n"
    "=================================== FAILURES ===================================\n"
    "____________________ test_is_newer_handles_double_digit_minor ___________________\n"
    "E       AssertionError: assert False\n"
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_versions.py::test_is_newer_handles_double_digit_minor - Ass...\n"
    "1 failed, 3 passed in 0.05s\n"
)


def test_raw_pytest_q_log_without_step_names_is_a_test_failure():
    # ``fix-repo --log-file`` knows neither the job nor the step, and ``-q`` prints no banner.
    classification = FailureClassifier().classify(
        _event("ci", "unknown", "FAILED tests/test_versions.py::test_x - Ass...", RAW_PYTEST_Q_LOG)
    )

    assert classification.category == "test_failure"
    assert classification.confidence >= 0.6


@pytest.mark.parametrize(
    "log",
    [
        "FAILED to fetch index\nerror: process failed\n",
        "build step failed after 3 attempts\n",
    ],
)
def test_logs_merely_saying_failed_stay_unknown(log):
    assert _category("ci", "unknown", "process failed", log) == "unknown"


def test_raw_pytest_log_with_a_missing_module_stays_a_dependency_failure():
    log = RAW_PYTEST_Q_LOG.replace("AssertionError: assert False", "ModuleNotFoundError: No module named 'requests'")
    assert _category("ci", "unknown", "FAILED tests/test_a.py::test_x", log) == "dependency_failure"


def test_security_scan_failure_escalates_even_when_the_patch_passes():
    proposal = RepairProposal(
        proposal_id="p",
        run_id="r",
        files_changed=("src/app.py",),
        patch="--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-a\n+b\n",
        rationale="remove key",
        expected_effect="scan passes",
        verification_plan=("gitleaks detect",),
    )
    evaluation = EvaluationResult(
        run_id="r",
        passed=True,
        patch_applied=True,
        target_verification_passed=True,
        regressions_detected=False,
        forbidden_changes_detected=False,
        checks=(),
        evidence=(),
    )
    classification = FailureClassifier().classify(
        _event("Gitleaks", "Run gitleaks/gitleaks-action@v3", "Leaks detected", "", "security")
    )
    decision = StaticPolicyEngine().evaluate(
        build_policy_context(proposal=proposal, evaluation=evaluation, classification=classification)
    )

    assert decision.outcome is PolicyOutcome.ESCALATE
    assert RULE_FAILURE_CATEGORY in decision.matched_rules

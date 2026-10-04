"""Foundation classifier: timeouts, environment mismatches, configuration errors and extra wording.

The new classes are a fallback behind the shared table, which experimental modules also use;
these tests pin both the new categories and the shared table's unchanged meaning.
"""

from __future__ import annotations

import pytest

from ci_failure_orchestrator.classifier import classify_error
from ci_failure_orchestrator.foundation.classifier import FailureClassifier, classify_text
from ci_failure_orchestrator.foundation.models import EvaluationResult, FailureEvent, RepairProposal
from ci_failure_orchestrator.foundation.policy import (
    RULE_FAILURE_CATEGORY,
    PolicyOutcome,
    StaticPolicyEngine,
    build_policy_context,
)


def _classify(step: str, message: str, log: str = ""):
    return FailureClassifier().classify(
        FailureEvent(
            event_id="e",
            run_id="r",
            source="github_actions",
            workflow="ci",
            job="build",
            failed_step=step,
            message=message,
            log_excerpt=log,
        )
    )


@pytest.mark.parametrize(
    ("step", "message", "category"),
    [
        ("Run tests", "urllib.error.URLError: <urlopen error [Errno -2] Name or service not known>", "network_failure"),
        ("Run tests", "curl: (6) Could not resolve host: registry.example.com", "network_failure"),
        (
            "Run tests",
            "ImportError: cannot import name 'parse' from 'fakelib' (/opt/fakelib/__init__.py)",
            "dependency_failure",
        ),
        (
            "Install",
            "ERROR: Cannot install a==1 and b==2 because these package versions have conflicting dependencies.",
            "dependency_failure",
        ),
        ("Install", "ERROR: Package 'demo' requires a different Python: 3.8.18 not in '>=3.10'", "environment_failure"),
        ("Install", 'error demo@1.0.0: The engine "node" is incompatible with this module.', "environment_failure"),
        (
            "Check configuration",
            "app.config.ConfigError: unknown setting 'retry_limt' in config/app.ini",
            "configuration_failure",
        ),
        (
            "Run tests",
            "The job running on runner GitHub Actions 3 has exceeded the maximum execution time of 10 minutes.",
            "timeout_failure",
        ),
        ("Run tests", "test_checkout timed out after 30s", "timeout_failure"),
    ],
)
def test_failure_types(step, message, category):
    assert _classify(step, message).category == category


def test_a_timeout_in_a_test_step_is_not_a_test_failure():
    classification = _classify("pytest", "Timeout >5.0s: test_wait_until_ready timed out")

    assert classification.category == "timeout_failure"
    assert "message=TIMEOUT" in classification.evidence


def test_explicit_flaky_markers_keep_timeouts_flaky():
    assert _classify("Run tests", "test timed out and is known intermittent").category == "flaky_failure"
    assert classify_text("flaky intermittent timed out waiting for condition")[0] == "FLAKY_TEST"


def test_the_shared_table_keeps_its_meaning_for_experimental_modules():
    assert classify_error("test_checkout timed out after 30s")[0] == "FLAKY_TEST"
    assert classify_error("ConfigError: unknown setting 'x'")[0] == "UNKNOWN"
    assert classify_error("Name or service not known")[0] == "UNKNOWN"


def test_fallback_never_overrides_a_shared_match():
    # "AssertionError" matches the shared table first; the network wording later in the
    # message does not turn a failing assertion into a network failure.
    assert classify_text("AssertionError: retried after Name or service not known")[0] == "TEST_ASSERTION"


@pytest.mark.parametrize(
    ("step", "message"),
    [
        (
            "Run tests",
            "The job running on runner GitHub Actions 3 has exceeded the maximum execution time of 10 minutes.",
        ),
        ("Install", "ERROR: Package 'demo' requires a different Python: 3.8.18 not in '>=3.10'"),
    ],
)
def test_timeouts_and_environment_mismatches_escalate_even_when_the_patch_passes(step, message):
    proposal = RepairProposal(
        proposal_id="p",
        run_id="r",
        files_changed=("src/poller.py",),
        patch="--- a/src/poller.py\n+++ b/src/poller.py\n@@ -1 +1 @@\n-a\n+b\n",
        rationale="fix",
        expected_effect="step passes",
        verification_plan=("python -m unittest",),
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
    decision = StaticPolicyEngine().evaluate(
        build_policy_context(proposal=proposal, evaluation=evaluation, classification=_classify(step, message))
    )

    assert decision.outcome is PolicyOutcome.ESCALATE
    assert RULE_FAILURE_CATEGORY in decision.matched_rules

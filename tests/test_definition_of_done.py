"""Tests for the evidence-backed Definition of Done evaluator."""

from ci_failure_orchestrator.definition_of_done import (
    REQUIRED_GATES,
    evaluate_definition_of_done,
)


def _complete_evidence():
    """Build evidence that satisfies every canonical gate."""

    evidence = {}
    for path, expected in REQUIRED_GATES.items():
        cursor = evidence
        parts = path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = expected[0]
    return evidence


def test_complete_evidence_is_production_done():
    """All required evidence should derive PRODUCTION_DONE."""

    result = evaluate_definition_of_done(_complete_evidence())

    assert result.done is True
    assert result.status == "PRODUCTION_DONE"
    assert result.failures == ()


def test_missing_evidence_fails_closed():
    """Omitted evidence must never be interpreted as completion."""

    evidence = _complete_evidence()
    del evidence["security"]["secrets_scan"]

    result = evaluate_definition_of_done(evidence)

    assert result.done is False
    assert result.status == "NOT_DONE"
    assert [failure.path for failure in result.failures] == ["security.secrets_scan"]
    assert result.failures[0].actual is None


def test_failed_gate_reports_expected_and_actual_values():
    """A failed gate should produce actionable machine-readable evidence."""

    evidence = _complete_evidence()
    evidence["tests"]["regression"] = "fail"

    result = evaluate_definition_of_done(evidence)
    payload = result.to_dict()

    assert payload["done"] is False
    assert payload["missing_or_failed_gates"] == [
        {
            "path": "tests.regression",
            "expected": ["pass"],
            "actual": "fail",
        }
    ]


def test_not_applicable_is_allowed_only_where_policy_explicitly_permits_it():
    """Optional production gates may use explicit not-applicable evidence."""

    evidence = _complete_evidence()
    evidence["tests"]["e2e"] = "not_applicable"
    evidence["operations"]["deployment"] = "not_applicable"
    evidence["operations"]["canary"] = "not_applicable"

    result = evaluate_definition_of_done(evidence)

    assert result.done is True

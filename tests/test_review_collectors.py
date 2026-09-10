from ci_failure_orchestrator.review_collectors import collect_coderabbit, collect_copilot, collect_sonarqube
from ci_failure_orchestrator.review_gate import ReviewSource, Severity


def test_coderabbit_normalizes_major_to_high() -> None:
    review = collect_coderabbit(
        {"completed": True, "findings": [{"severity": "major", "rule_id": "CR-1", "message": "problem"}]},
        evidence_ref="review:1",
    )
    assert review.completed is True
    assert review.source is ReviewSource.CODERABBIT
    assert review.findings[0].severity is Severity.HIGH


def test_unknown_severity_is_conservatively_high() -> None:
    review = collect_copilot(
        {"completed": True, "findings": [{"severity": "mystery", "message": "unknown classification"}]},
        evidence_ref="review:2",
    )
    assert review.findings[0].severity is Severity.HIGH


def test_missing_payload_is_incomplete() -> None:
    review = collect_sonarqube(None, evidence_ref=None)
    assert review.completed is False


def test_malformed_findings_is_incomplete() -> None:
    review = collect_coderabbit({"completed": True, "findings": "not-a-list"}, evidence_ref="review:3")
    assert review.completed is False

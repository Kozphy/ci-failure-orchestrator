from ci_failure_orchestrator.review_gate import (
    GateDecision,
    ProviderReview,
    ReviewAggregator,
    ReviewFinding,
    ReviewPolicyEngine,
    ReviewSource,
    Severity,
    VerificationResult,
)


def _clean(source: ReviewSource) -> ProviderReview:
    return ProviderReview(source=source, completed=True, evidence_ref=f"evidence:{source.value}")


def _verified() -> VerificationResult:
    return VerificationResult(passed=True, evidence_refs=("evidence:independent",))


def test_pr_ready_requires_all_three_reviews_and_verification() -> None:
    bundle = ReviewAggregator().aggregate((_clean(ReviewSource.CODERABBIT), _clean(ReviewSource.COPILOT), _clean(ReviewSource.SONARQUBE)), _verified())
    result = ReviewPolicyEngine().evaluate(bundle)
    assert result.decision is GateDecision.PR_READY
    assert result.reasons == ()


def test_missing_provider_fails_closed() -> None:
    bundle = ReviewAggregator().aggregate((_clean(ReviewSource.CODERABBIT), _clean(ReviewSource.SONARQUBE)), _verified())
    result = ReviewPolicyEngine().evaluate(bundle)
    assert result.decision is GateDecision.BLOCK
    assert any("copilot" in reason for reason in result.reasons)


def test_high_severity_finding_blocks_merge() -> None:
    finding = ReviewFinding(ReviewSource.CODERABBIT, Severity.HIGH, "CR-1", "unsafe behavior")
    coderabbit = ProviderReview(ReviewSource.CODERABBIT, True, (finding,), "evidence:coderabbit")
    bundle = ReviewAggregator().aggregate((coderabbit, _clean(ReviewSource.COPILOT), _clean(ReviewSource.SONARQUBE)), _verified())
    assert ReviewPolicyEngine().evaluate(bundle).decision is GateDecision.BLOCK


def test_explicit_blocking_medium_finding_blocks_merge() -> None:
    finding = ReviewFinding(ReviewSource.COPILOT, Severity.MEDIUM, "CP-1", "policy finding", blocking=True)
    copilot = ProviderReview(ReviewSource.COPILOT, True, (finding,), "evidence:copilot")
    bundle = ReviewAggregator().aggregate((_clean(ReviewSource.CODERABBIT), copilot, _clean(ReviewSource.SONARQUBE)), _verified())
    assert ReviewPolicyEngine().evaluate(bundle).decision is GateDecision.BLOCK


def test_failed_independent_verification_blocks_merge() -> None:
    verification = VerificationResult(passed=False, evidence_refs=("evidence:failed-test",))
    bundle = ReviewAggregator().aggregate(tuple(_clean(source) for source in ReviewSource), verification)
    assert ReviewPolicyEngine().evaluate(bundle).decision is GateDecision.BLOCK


def test_missing_evidence_blocks_merge() -> None:
    no_evidence = ProviderReview(ReviewSource.SONARQUBE, completed=True)
    bundle = ReviewAggregator().aggregate((_clean(ReviewSource.CODERABBIT), _clean(ReviewSource.COPILOT), no_evidence), _verified())
    assert ReviewPolicyEngine().evaluate(bundle).decision is GateDecision.BLOCK


def test_duplicate_provider_is_rejected() -> None:
    reviews = (_clean(ReviewSource.CODERABBIT), _clean(ReviewSource.CODERABBIT))
    try:
        ReviewAggregator().aggregate(reviews, _verified())
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate source must be rejected")

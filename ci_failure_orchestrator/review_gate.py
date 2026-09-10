"""Multi-source PR review aggregation and fail-closed policy decisions.

Normalizes CodeRabbit, Copilot, and SonarQube findings into one deterministic
policy decision. External provider collection is intentionally kept outside
this module so provider API failures cannot silently become approvals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class Severity(str, Enum):
    """Normalized finding severity."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewSource(str, Enum):
    """Supported independent review sources."""

    CODERABBIT = "coderabbit"
    COPILOT = "copilot"
    SONARQUBE = "sonarqube"


class GateDecision(str, Enum):
    """Final merge-gate decision."""

    PR_READY = "PR_READY"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class ReviewFinding:
    """One normalized finding emitted by a review provider."""

    source: ReviewSource
    severity: Severity
    rule_id: str
    message: str
    blocking: bool = False


@dataclass(frozen=True)
class ProviderReview:
    """Review result from one required provider."""

    source: ReviewSource
    completed: bool
    findings: tuple[ReviewFinding, ...] = ()
    evidence_ref: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    """Independent verification evidence required after review aggregation."""

    passed: bool
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewBundle:
    """Aggregated provider reviews plus independent verification."""

    reviews: tuple[ProviderReview, ...]
    verification: VerificationResult


@dataclass(frozen=True)
class PolicyDecision:
    """Machine-readable merge decision with explicit reasons."""

    decision: GateDecision
    reasons: tuple[str, ...] = ()
    finding_count: int = 0
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)


class ReviewAggregator:
    """Build a complete bundle while rejecting duplicate provider reports."""

    def aggregate(
        self,
        reviews: Iterable[ProviderReview],
        verification: VerificationResult,
    ) -> ReviewBundle:
        """Aggregate provider outputs without allowing duplicate identities."""
        items = tuple(reviews)
        sources = [item.source for item in items]
        if len(sources) != len(set(sources)):
            raise ValueError("duplicate review source")
        return ReviewBundle(reviews=items, verification=verification)


class ReviewPolicyEngine:
    """Fail-closed policy engine for multi-source PR review evidence."""

    REQUIRED_SOURCES = frozenset(ReviewSource)
    BLOCKING_SEVERITIES = frozenset({Severity.HIGH, Severity.CRITICAL})

    def evaluate(self, bundle: ReviewBundle) -> PolicyDecision:
        """Return PR_READY only when every required control is satisfied."""
        by_source = {review.source: review for review in bundle.reviews}
        reasons: list[str] = []

        missing = self.REQUIRED_SOURCES - set(by_source)
        if missing:
            reasons.append(
                "missing required review sources: "
                + ", ".join(sorted(source.value for source in missing))
            )

        incomplete = [
            source.value
            for source, review in by_source.items()
            if not review.completed
        ]
        if incomplete:
            reasons.append("incomplete reviews: " + ", ".join(sorted(incomplete)))

        findings = tuple(
            finding
            for review in bundle.reviews
            for finding in review.findings
        )
        blocking = [
            finding
            for finding in findings
            if finding.blocking or finding.severity in self.BLOCKING_SEVERITIES
        ]
        if blocking:
            reasons.append(f"{len(blocking)} blocking review finding(s)")

        missing_review_evidence = [
            review.source.value
            for review in bundle.reviews
            if review.completed and not review.evidence_ref
        ]
        if missing_review_evidence:
            reasons.append(
                "missing review evidence: "
                + ", ".join(sorted(missing_review_evidence))
            )

        if not bundle.verification.passed:
            reasons.append("independent verification failed")
        if not bundle.verification.evidence_refs:
            reasons.append("independent verification evidence missing")

        evidence = tuple(
            review.evidence_ref
            for review in bundle.reviews
            if review.evidence_ref is not None
        ) + bundle.verification.evidence_refs

        decision = GateDecision.BLOCK if reasons else GateDecision.PR_READY
        return PolicyDecision(
            decision=decision,
            reasons=tuple(reasons),
            finding_count=len(findings),
            evidence_refs=evidence,
        )

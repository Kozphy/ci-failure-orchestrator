"""Provider payload adapters for the multi-review policy gate.

These adapters are deliberately pure: callers fetch provider data and pass the
payload here. Unknown or malformed states become incomplete reviews so the
policy engine fails closed rather than silently approving a PR.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .review_gate import ProviderReview, ReviewFinding, ReviewSource, Severity


def _severity(value: object) -> Severity:
    """Normalize common provider severities conservatively."""
    normalized = str(value or "").strip().lower()
    aliases = {
        "info": Severity.INFO,
        "minor": Severity.LOW,
        "low": Severity.LOW,
        "medium": Severity.MEDIUM,
        "major": Severity.HIGH,
        "high": Severity.HIGH,
        "critical": Severity.CRITICAL,
        "blocker": Severity.CRITICAL,
    }
    return aliases.get(normalized, Severity.HIGH)


def _finding(source: ReviewSource, raw: Mapping[str, Any]) -> ReviewFinding:
    """Convert a provider finding into the normalized model."""
    return ReviewFinding(
        source=source,
        severity=_severity(raw.get("severity")),
        rule_id=str(raw.get("rule_id") or raw.get("rule") or "unknown"),
        message=str(raw.get("message") or raw.get("body") or "unspecified finding"),
        blocking=bool(raw.get("blocking", False)),
    )


def collect_review(
    source: ReviewSource,
    payload: Mapping[str, Any] | None,
    *,
    evidence_ref: str | None,
) -> ProviderReview:
    """Normalize one provider payload; invalid input is an incomplete review."""
    if not payload:
        return ProviderReview(source=source, completed=False, evidence_ref=evidence_ref)

    raw_findings = payload.get("findings", ())
    if not isinstance(raw_findings, Sequence) or isinstance(raw_findings, (str, bytes)):
        return ProviderReview(source=source, completed=False, evidence_ref=evidence_ref)

    try:
        findings = tuple(
            _finding(source, item)
            for item in raw_findings
            if isinstance(item, Mapping)
        )
    except (TypeError, ValueError):
        return ProviderReview(source=source, completed=False, evidence_ref=evidence_ref)

    completed = payload.get("completed") is True
    return ProviderReview(
        source=source,
        completed=completed,
        findings=findings,
        evidence_ref=evidence_ref,
    )


def collect_coderabbit(payload: Mapping[str, Any] | None, *, evidence_ref: str | None) -> ProviderReview:
    """Normalize a CodeRabbit review payload."""
    return collect_review(ReviewSource.CODERABBIT, payload, evidence_ref=evidence_ref)


def collect_copilot(payload: Mapping[str, Any] | None, *, evidence_ref: str | None) -> ProviderReview:
    """Normalize a Copilot review payload."""
    return collect_review(ReviewSource.COPILOT, payload, evidence_ref=evidence_ref)


def collect_sonarqube(payload: Mapping[str, Any] | None, *, evidence_ref: str | None) -> ProviderReview:
    """Normalize a SonarQube analysis payload."""
    return collect_review(ReviewSource.SONARQUBE, payload, evidence_ref=evidence_ref)

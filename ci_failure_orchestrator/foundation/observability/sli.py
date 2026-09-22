"""Explicit SLI definitions and calculation for foundation runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .summary import RunMetricsSummary


@dataclass(frozen=True)
class SLIDefinition:
    sli_id: str
    name: str
    purpose: str
    numerator_desc: str
    denominator_desc: str
    eligibility: str
    limitations: str


@dataclass(frozen=True)
class SLIResult:
    sli_id: str
    name: str
    numerator: int
    denominator: int
    value: float | None
    insufficient_data: bool

    def to_dict(self) -> dict:
        return {
            "sli_id": self.sli_id,
            "name": self.name,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
            "display": (
                f"{self.numerator}/{self.denominator}"
                if self.denominator
                else "n/a (zero denominator)"
            ),
            "insufficient_data": self.insufficient_data,
        }


def _ratio(num: int, den: int) -> float | None:
    if den == 0:
        return None
    return num / den


def _runtime(summaries: Sequence[RunMetricsSummary]) -> list[RunMetricsSummary]:
    return [s for s in summaries if s.source == "runtime"]


SLI_CATALOG: tuple[SLIDefinition, ...] = (
    SLIDefinition(
        sli_id="SLI-001",
        name="automated_run_success_rate",
        purpose="Technical success among eligible automated repair runs",
        numerator_desc="eligible runs with technical_status=PASS",
        denominator_desc="eligible runtime repair runs",
        eligibility="source=runtime AND eligible_repair",
        limitations="Does not measure governance approval or production repairability",
    ),
    SLIDefinition(
        sli_id="SLI-002",
        name="safe_approval_rate",
        purpose="Descriptive share of technical PASS runs that were policy APPROVE",
        numerator_desc="technical PASS + policy APPROVE",
        denominator_desc="technical PASS runtime runs with a policy decision",
        eligibility="runtime technical PASS with policy_outcome set",
        limitations="Descriptive only — higher is not inherently better",
    ),
    SLIDefinition(
        sli_id="SLI-003",
        name="escalation_rate",
        purpose="Operational load: AWAITING_HUMAN among policy-reviewed runs",
        numerator_desc="workflow AWAITING_HUMAN",
        denominator_desc="runs with a policy decision",
        eligibility="runtime runs with policy_outcome set",
        limitations="Neither good nor bad by itself",
    ),
    SLIDefinition(
        sli_id="SLI-004",
        name="retry_rate",
        purpose="Share of eligible runs that retried at least once",
        numerator_desc="retries >= 1",
        denominator_desc="eligible runtime runs",
        eligibility="source=runtime AND eligible_repair",
        limitations="Uses Phase 7 attempt/retry semantics",
    ),
    SLIDefinition(
        sli_id="SLI-005",
        name="bounded_retry_compliance",
        purpose="Control correctness: retrying runs respect configured stop reasons",
        numerator_desc="retrying runs with a bounded stop reason",
        denominator_desc="runs with retries >= 1",
        eligibility="runtime runs with retries >= 1",
        limitations="Does not prove optimality of stop choice",
    ),
    SLIDefinition(
        sli_id="SLI-006",
        name="policy_execution_coverage",
        purpose="Policy Gate executed when technical PASS required review",
        numerator_desc="technical PASS with policy decision present",
        denominator_desc="technical PASS runtime runs",
        eligibility="runtime technical PASS",
        limitations="Coverage only — not golden policy accuracy (Phase 12)",
    ),
    SLIDefinition(
        sli_id="SLI-007",
        name="security_containment_compliance",
        purpose="Containment after detection for block-required events",
        numerator_desc="security_blocks",
        denominator_desc="security_findings (block-required detections)",
        eligibility="runtime summaries with security_findings > 0",
        limitations="Not detection recall; no SecurityFinding module in foundation",
    ),
    SLIDefinition(
        sli_id="SLI-008",
        name="audit_completeness",
        purpose="Completed automated runs with required evidence",
        numerator_desc="audit_complete=True",
        denominator_desc="runtime runs with audit_complete measured",
        eligibility="runtime runs where audit was assessed",
        limitations="Does not prove tamper resistance or evidence correctness",
    ),
    SLIDefinition(
        sli_id="SLI-009",
        name="persistence_reliability",
        purpose="Runs without critical persistence failure",
        numerator_desc="persistence_ok=True",
        denominator_desc="all runtime runs in population",
        eligibility="source=runtime",
        limitations="Derived from workflow status / summary flag",
    ),
    SLIDefinition(
        sli_id="SLI-010",
        name="run_latency",
        purpose="Automated run duration distribution (not a ratio SLI)",
        numerator_desc="n/a (distribution)",
        denominator_desc="runtime runs with duration_seconds",
        eligibility="runtime runs with duration",
        limitations="Local timing only; tiny samples are not statistically stable",
    ),
)

_BOUNDED_STOPS = frozenset(
    {
        "SUCCESS",
        "MAX_ATTEMPTS_EXHAUSTED",
        "IDENTICAL_PROPOSAL_REPEATED",
        "IDENTICAL_FAILURE_REPEATED",
        "NO_PROGRESS",
        "UNRECOVERABLE_FAILURE",
        "INVALID_PROPOSAL",
        "SECURITY_BOUNDARY_HIT",
        "INSUFFICIENT_EVIDENCE",
    }
)


def compute_slis(summaries: Sequence[RunMetricsSummary]) -> list[SLIResult]:
    runtime = _runtime(summaries)
    eligible = [s for s in runtime if s.eligible_repair]
    results: list[SLIResult] = []

    # SLI-001
    den = len(eligible)
    num = sum(1 for s in eligible if s.technical_status == "PASS")
    results.append(
        SLIResult("SLI-001", "automated_run_success_rate", num, den, _ratio(num, den), den == 0)
    )

    # SLI-002
    pass_with_policy = [
        s
        for s in runtime
        if s.technical_status == "PASS" and s.policy_outcome
    ]
    den = len(pass_with_policy)
    num = sum(1 for s in pass_with_policy if s.policy_outcome == "APPROVE")
    results.append(
        SLIResult("SLI-002", "safe_approval_rate", num, den, _ratio(num, den), den == 0)
    )

    # SLI-003
    policy_reviewed = [s for s in runtime if s.policy_outcome]
    den = len(policy_reviewed)
    num = sum(1 for s in policy_reviewed if s.workflow_status == "AWAITING_HUMAN")
    results.append(
        SLIResult("SLI-003", "escalation_rate", num, den, _ratio(num, den), den == 0)
    )

    # SLI-004
    den = len(eligible)
    num = sum(1 for s in eligible if s.retries >= 1)
    results.append(
        SLIResult("SLI-004", "retry_rate", num, den, _ratio(num, den), den == 0)
    )

    # SLI-005
    retrying = [s for s in runtime if s.retries >= 1]
    den = len(retrying)
    num = sum(1 for s in retrying if (s.stop_reason or "") in _BOUNDED_STOPS)
    results.append(
        SLIResult(
            "SLI-005",
            "bounded_retry_compliance",
            num,
            den,
            _ratio(num, den),
            den == 0,
        )
    )

    # SLI-006
    tech_pass = [s for s in runtime if s.technical_status == "PASS"]
    den = len(tech_pass)
    num = sum(1 for s in tech_pass if s.policy_outcome)
    results.append(
        SLIResult(
            "SLI-006",
            "policy_execution_coverage",
            num,
            den,
            _ratio(num, den),
            den == 0,
        )
    )

    # SLI-007
    findings = sum(s.security_findings for s in runtime)
    blocks = sum(s.security_blocks for s in runtime)
    results.append(
        SLIResult(
            "SLI-007",
            "security_containment_compliance",
            blocks,
            findings,
            _ratio(blocks, findings),
            findings == 0,
        )
    )

    # SLI-008
    audited = [s for s in runtime if s.audit_complete is not None]
    den = len(audited)
    num = sum(1 for s in audited if s.audit_complete is True)
    results.append(
        SLIResult("SLI-008", "audit_completeness", num, den, _ratio(num, den), den == 0)
    )

    # SLI-009
    den = len(runtime)
    num = sum(1 for s in runtime if s.persistence_ok)
    results.append(
        SLIResult(
            "SLI-009",
            "persistence_reliability",
            num,
            den,
            _ratio(num, den),
            den == 0,
        )
    )

    # SLI-010 — distribution encoded as count in denominator; value unused
    timed = [s for s in runtime if s.duration_seconds is not None]
    results.append(
        SLIResult(
            "SLI-010",
            "run_latency",
            len(timed),
            len(timed),
            None,
            len(timed) == 0,
        )
    )
    return results

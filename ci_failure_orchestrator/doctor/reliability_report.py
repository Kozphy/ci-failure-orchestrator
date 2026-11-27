"""One-run or one-log reliability report. It does not measure a before/after improvement."""

from __future__ import annotations

from typing import Any

from ..service.untrusted import clean_untrusted
from .diagnose import Diagnosis

REPORT_SCHEMA = "ci-doctor.reliability-report.v1"


def _text(value: object) -> str:
    return clean_untrusted("" if value is None else str(value))


def build_reliability_report(diagnosis: Diagnosis) -> dict[str, Any]:
    """Build the report dict from one diagnosis. Missing history stays null, not zero."""
    top = diagnosis.findings[0] if diagnosis.findings else None
    policy = diagnosis.policy.outcome if diagnosis.policy is not None else "none"
    finding = None
    if top is not None:
        finding = {
            "id": "F-1",
            "severity": "high" if policy == "ESCALATE" else "medium",
            "severity_basis": "policy preview outcome, not a measured incident rate",
            "source_evidence": _text(top.message),
            "evidence_line": top.evidence_line,
            "reproduction": [_text(step) for step in diagnosis.verification],
            "confidence": _text(top.confidence),
            "confidence_kind": "heuristic",
            "recommended_remediation": _text(diagnosis.next_step),
            "validation_status": "not_executed",
            "category": _text(top.category),
            "job": _text(top.job),
            "step": _text(top.step),
        }
    return {
        "schema": REPORT_SCHEMA,
        "evidence_class": "single_diagnosis",
        "executive_summary": _text(
            f"Top classification is {top.category}." if top else "No failed job was classified."
        ),
        "repository": _text(diagnosis.repository) or None,
        "workflow_scope": {
            "source": _text(diagnosis.source),
            "run_id": diagnosis.run_id,
            "run_url": _text(diagnosis.run_url) or None,
        },
        "evaluation_period": None,
        "evidence_sources": [_text(diagnosis.source)],
        "observed_failures": [] if finding is None else [finding],
        "failure_classifications": [] if top is None else [_text(top.category)],
        "frequency": {"observations": 1 if top else 0, "recurrence": None},
        "reliability_risks": [] if finding is None else [finding["id"]],
        "repair_recommendations": [] if finding is None else [finding["recommended_remediation"]],
        "security_considerations": [
            "Log text was treated as untrusted data.",
            "Secret patterns known to the redactor were replaced. This is not a guarantee.",
            "Recommended commands were not executed.",
        ],
        "validation_results": {"recommendation_executed": False, "policy_status": policy},
        "limitations": [
            "One diagnosis is not a 30-day reliability rate.",
            "No baseline and no post-change measurement are included.",
            "No business-savings figure is computed.",
        ],
        "recommended_next_actions": [
            "A human reviews the finding before any patch or push.",
        ],
        "diagnosis_id": _text(diagnosis.diagnosis_id),
    }


def render_reliability_markdown(report: dict[str, Any]) -> str:
    """Render the report sections. Strings are already redacted by the builder."""
    findings = report["observed_failures"]
    lines = [
        "# CI Reliability Audit",
        "",
        "Evidence class: single diagnosis. Not a multi-run audit and not a customer engagement.",
        "",
        "## 1. Executive summary",
        "",
        str(report["executive_summary"]),
        "",
        "## 2. Repository and workflow scope",
        "",
        f"Repository: {report['repository'] or 'not provided'}",
        f"Source: {report['workflow_scope']['source']}",
        f"Run: {report['workflow_scope']['run_id'] or 'not a GitHub run'}",
        "",
        "## 3. Evaluation period",
        "",
        "Not a time window. This report covers the one log or run that was supplied.",
        "",
        "## 4. Evidence sources",
        "",
        ", ".join(report["evidence_sources"]) or "none",
        "",
        "## 5. Observed CI failures",
        "",
    ]
    if not findings:
        lines.append("No failed job was present in the diagnosis.")
    for finding in findings:
        lines.extend(
            [
                f"### {finding['id']}",
                "",
                f"- Severity: {finding['severity']} ({finding['severity_basis']})",
                f"- Category: {finding['category']}",
                f"- Job: {finding['job']}",
                f"- Step: {finding['step'] or 'not named'}",
                f"- Evidence: {finding['source_evidence']}",
                f"- Evidence line: {finding['evidence_line']}",
                f"- Confidence: {finding['confidence']} ({finding['confidence_kind']})",
                f"- Reproduction: {'; '.join(finding['reproduction']) or 'none recorded'}",
                f"- Remediation: {finding['recommended_remediation']}",
                f"- Validation status: {finding['validation_status']}",
                "",
            ]
        )
    lines.extend(
        [
            "## 6. Failure classifications",
            "",
            ", ".join(report["failure_classifications"]) or "none",
            "",
            "## 7. Frequency and recurrence",
            "",
            f"Observations in this input: {report['frequency']['observations']}. Recurrence was not measured.",
            "",
            "## 8. Reliability risks",
            "",
            ", ".join(report["reliability_risks"]) or "none",
            "",
            "## 9. Repair recommendations",
            "",
        ]
    )
    if report["repair_recommendations"]:
        lines.extend(f"- {item}" for item in report["repair_recommendations"])
    else:
        lines.append("None.")
    lines.extend(["", "## 10. Security considerations", ""])
    lines.extend(f"- {item}" for item in report["security_considerations"])
    lines.extend(
        [
            "",
            "## 11. Validation results",
            "",
            f"Policy status: {report['validation_results']['policy_status']}.",
            "The recommended remediation was not executed by this report.",
            "",
            "## 12. Limitations and unverified assumptions",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(["", "## 13. Recommended next actions", ""])
    lines.extend(f"- {item}" for item in report["recommended_next_actions"])
    lines.append("")
    return "\n".join(lines)

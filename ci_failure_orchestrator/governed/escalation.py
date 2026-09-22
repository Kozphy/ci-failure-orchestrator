"""Actionable human escalation packaging."""

from __future__ import annotations

from .models import (
    EvaluationResult,
    FailureClassification,
    FailureContext,
    HumanEscalation,
    PolicyDecision,
    RepairProposal,
    utc_now,
)


def build_escalation(
    *,
    run_id: str,
    context: FailureContext,
    classification: FailureClassification,
    proposal: RepairProposal | None,
    evaluation: EvaluationResult | None,
    policy: PolicyDecision | None,
    attempted: tuple[str, ...] = (),
) -> HumanEscalation:
    why_parts = []
    if policy:
        why_parts.append(f"policy={policy.outcome.value}:{','.join(policy.reasons)}")
    if classification.failure_class in {"unknown", "infrastructure_failure", "network_failure"}:
        why_parts.append(f"class={classification.failure_class}")
    if evaluation and not evaluation.passed:
        why_parts.append("evaluation_not_passed")
    if not why_parts:
        why_parts.append("explicit_escalation_requested")

    return HumanEscalation(
        run_id=run_id,
        why="; ".join(why_parts),
        failure_summary=context.summary,
        attempted_repairs=attempted,
        proposed_change=(
            proposal.reasoning_summary if proposal else "No safe proposal produced"
        ),
        evaluation_evidence=evaluation.evidence if evaluation else (),
        remaining_uncertainty=classification.uncertainty,
        recommended_review_action=(
            "Review proposed diff scope, confirm security/policy impact, "
            "then approve a bounded retry or take manual remediation."
        ),
        timestamp=utc_now(),
    )

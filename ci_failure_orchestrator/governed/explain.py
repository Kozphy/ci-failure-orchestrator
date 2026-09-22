"""Human-readable run summaries (decision traceability)."""

from __future__ import annotations

from .pipeline import PipelineResult
from .store import StateStore


def explain_result(result: PipelineResult) -> str:
    classification = result.classification
    evaluation = result.evaluation
    policy = result.policy
    lines = [
        f"Run: {result.run_id}",
        "",
        "Failure:",
        f"  {(classification.failure_class if classification else 'n/a')}",
        "",
        "Classification:",
        f"  class={getattr(classification, 'failure_class', 'n/a')}",
        f"  confidence={getattr(classification, 'confidence', 'n/a')} (heuristic)",
        f"  uncertainty={getattr(classification, 'uncertainty', 'n/a')}",
        "",
        "Attempts:",
        f"  {result.attempts}",
        "",
        "Evaluation:",
    ]
    if evaluation:
        lines.extend(
            [
                f"  passed: {evaluation.passed}",
                f"  target check: {evaluation.target_check_passed}",
                f"  regression_free: {evaluation.regression_free}",
                f"  policy_safe: {evaluation.policy_safe}",
                f"  evidence: {', '.join(evaluation.evidence)}",
            ]
        )
    else:
        lines.append("  (none)")

    lines.extend(["", "Decision:", f"  state={result.state.value}"])
    if policy:
        lines.append(f"  policy={policy.outcome.value} ({', '.join(policy.reasons)})")
    if result.escalation:
        lines.extend(
            [
                "",
                "Human escalation:",
                f"  why: {result.escalation.why}",
                f"  action: {result.escalation.recommended_review_action}",
            ]
        )
    return "\n".join(lines) + "\n"


def explain_stored_run(store: StateStore, run_id: str) -> str:
    state = store.load_run(run_id)
    if state is None:
        return f"Run: {run_id}\n\nNot found in store.\n"
    return (
        f"Run: {run_id}\n\n"
        f"Status: {state.get('status')}\n"
        f"Attempts: {len(state.get('attempts') or [])}\n"
        f"Escalated: {state.get('escalated')}\n"
    )

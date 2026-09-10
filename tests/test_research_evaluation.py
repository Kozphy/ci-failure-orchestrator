from __future__ import annotations

from ci_failure_orchestrator.research_evaluation import (
    CaseOutcome,
    bootstrap_paired_uplift_ci,
    canonical_json_digest,
    mcnemar_exact_p_value,
    summarize_paired_outcomes,
)


def test_paired_summary_detects_proposed_uplift() -> None:
    outcomes = [
        CaseOutcome("a", "x", "x", "y", True, False),
        CaseOutcome("b", "x", "x", "y", True, False),
        CaseOutcome("c", "x", "x", "x", True, True),
        CaseOutcome("d", "x", "y", "x", False, True),
    ]

    metrics = summarize_paired_outcomes(outcomes, bootstrap_trials=500, seed=7)

    assert metrics.cases == 4
    assert metrics.proposed_accuracy == 0.75
    assert metrics.baseline_accuracy == 0.5
    assert metrics.absolute_uplift == 0.25
    assert metrics.discordant_proposed_wins == 2
    assert metrics.discordant_baseline_wins == 1


def test_bootstrap_is_deterministic_for_fixed_seed() -> None:
    outcomes = [
        CaseOutcome("a", "x", "x", "y", True, False),
        CaseOutcome("b", "x", "x", "x", True, True),
    ]
    assert bootstrap_paired_uplift_ci(outcomes, trials=100, seed=11) == bootstrap_paired_uplift_ci(
        outcomes, trials=100, seed=11
    )


def test_exact_mcnemar_handles_no_discordance() -> None:
    assert mcnemar_exact_p_value(0, 0) == 1.0


def test_digest_is_order_independent_for_mappings() -> None:
    assert canonical_json_digest({"a": 1, "b": 2}) == canonical_json_digest({"b": 2, "a": 1})

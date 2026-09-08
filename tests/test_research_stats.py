import pytest

from ci_failure_orchestrator.research_stats import compare_paired_binary, wilson_interval


def test_wilson_interval_contains_observed_rate() -> None:
    estimate = wilson_interval(8, 10)
    assert estimate.rate == 0.8
    assert 0.0 <= estimate.ci95_low <= estimate.rate
    assert estimate.rate <= estimate.ci95_high <= 1.0


def test_wilson_interval_handles_boundaries() -> None:
    zero = wilson_interval(0, 10)
    full = wilson_interval(10, 10)
    assert zero.ci95_low == 0.0
    assert full.ci95_high == 1.0


def test_wilson_interval_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError):
        wilson_interval(1, 0)
    with pytest.raises(ValueError):
        wilson_interval(11, 10)


def test_paired_binary_comparison_counts_wins_losses_and_ties() -> None:
    result = compare_paired_binary(
        [True, True, False, False],
        [False, True, True, False],
    )
    assert result.cases == 4
    assert result.a_wins == 1
    assert result.b_wins == 1
    assert result.ties == 2
    assert result.absolute_rate_delta == 0.0


def test_paired_binary_comparison_rejects_unpaired_input() -> None:
    with pytest.raises(ValueError):
        compare_paired_binary([True], [])
    with pytest.raises(ValueError):
        compare_paired_binary([], [])

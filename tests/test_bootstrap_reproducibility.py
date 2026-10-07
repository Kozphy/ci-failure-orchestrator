import pytest

from research.stats import bootstrap, mcnemar_exact, mean_of, paired_bootstrap

VALUES = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 1.0]


def test_same_seed_gives_identical_intervals():
    a = bootstrap(VALUES, mean_of, seed=20261007, resamples=500)
    b = bootstrap(VALUES, mean_of, seed=20261007, resamples=500)
    assert a == b
    assert a["low"] <= a["estimate"] <= a["high"]
    assert a["seed"] == 20261007 and a["resamples"] == 500


def test_different_seed_changes_resamples_not_the_estimate():
    values = [i / 29 for i in range(30)]
    a = bootstrap(values, mean_of, seed=1, resamples=500)
    b = bootstrap(values, mean_of, seed=2, resamples=500)
    assert a["estimate"] == b["estimate"]
    assert (a["low"], a["high"]) != (b["low"], b["high"])


def test_empty_input_reports_a_reason_instead_of_zero():
    result = bootstrap([], mean_of, seed=1)
    assert result["estimate"] is None and result["reason"]


def test_paired_bootstrap_is_reproducible_and_labels_the_share():
    a = [1.0, 1.0, 0.0, 1.0, 0.0]
    b = [0.0, 1.0, 0.0, 0.0, 0.0]
    first = paired_bootstrap(a, b, seed=3, resamples=400)
    assert first == paired_bootstrap(a, b, seed=3, resamples=400)
    assert first["estimate"] == pytest.approx(0.4)
    assert 0.0 <= first["share_resamples_diff_le_0"] <= 1.0
    with pytest.raises(ValueError):
        paired_bootstrap([1.0], [1.0, 0.0], seed=3)


def test_exact_mcnemar():
    result = mcnemar_exact([True] * 5 + [False] * 5, [False] * 5 + [False] * 5)
    assert result["b10"] == 5 and result["b01"] == 0
    assert result["p_value"] == pytest.approx(0.0625)
    undefined = mcnemar_exact([True, False], [True, False])
    assert undefined["p_value"] is None and undefined["reason"]

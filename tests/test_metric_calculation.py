import pytest
from _research_factories import case_run, facts

from research.metrics import candidate_gate_metrics, classification_report, repair_metrics
from research.repair import p_composed, r_green
from research.stats import wilson


def test_classification_report_matches_hand_computation():
    pairs = [("a", "a"), ("a", "b"), ("b", "b"), ("b", None)]
    report = classification_report(pairs)
    assert report["accuracy"] == pytest.approx(0.5)
    assert report["per_class"]["a"]["precision"] == pytest.approx(1.0)
    assert report["per_class"]["a"]["recall"] == pytest.approx(0.5)
    assert report["per_class"]["b"]["precision"] == pytest.approx(0.5)
    assert report["per_class"]["b"]["recall"] == pytest.approx(0.5)
    assert report["macro_f1"] == pytest.approx((2 / 3 + 0.5) / 2)
    assert report["confusion"]["b"]["<none>"] == 1


def test_empty_classification_report_is_unavailable_not_zero():
    report = classification_report([])
    assert report["accuracy"] is None and report["reason"]


def test_wilson_interval_known_values():
    zero = wilson(0, 10)
    assert zero["estimate"] == 0.0 and zero["low"] == 0.0
    assert zero["high"] == pytest.approx(0.2775, abs=1e-3)
    half = wilson(5, 10)
    assert half["low"] == pytest.approx(0.2366, abs=1e-3) and half["high"] == pytest.approx(0.7634, abs=1e-3)
    empty = wilson(0, 0)
    assert empty["estimate"] is None and empty["reason"] == "n=0"


def test_repair_rates_use_the_case_as_the_unit():
    ordered_a = [facts("fake", "fake_fix", case_id="a", policy="REJECT", verified=False),
                 facts("good", "correct", case_id="a")]
    ordered_b = [facts("wrong", "semantically_wrong", case_id="b", oracle=False)]
    runs = [
        case_run("a", ordered_a, [r_green("R-GREEN-k", "a", ordered_a, 3), p_composed("P-composed", "a", ordered_a, 3)]),
        case_run("b", ordered_b, [r_green("R-GREEN-k", "b", ordered_b, 3), p_composed("P-composed", "b", ordered_b, 3)]),
    ]
    metrics = repair_metrics(runs, budget=3, seed=1, resamples=50)
    green = metrics["R-GREEN-k"]
    assert green["n_cases"] == 2
    assert green["green_but_wrong_rate"]["k"] == 2
    assert green["unsafe_remediation_rate"]["k"] == 1
    assert green["verified_repair_rate"]["k"] == 0
    p = metrics["P-composed"]
    assert p["policy_rejection_rate"]["k"] == 1
    assert p["green_but_wrong_rate"]["k"] == 1
    assert p["missed_correct_repair_rate"]["k"] == 1
    assert p["cost_usd_total"]["value"] is None and p["cost_usd_total"]["reason"]


def test_gate_metrics_are_order_independent_counts_over_green_candidates():
    ordered = [facts("fake", "fake_fix", policy="REJECT", verified=False, verified_no_policy=False),
               facts("wrong", "semantically_wrong", oracle=False),
               facts("good", "correct"),
               facts("noop", "no_op", ci_green=False, verified=False)]
    gates = candidate_gate_metrics([case_run("c", ordered, [])])
    assert gates["n_green_candidates"] == 3
    assert gates["gates"]["ci_green_only"]["accepted_incorrect"]["k"] == 2
    assert gates["gates"]["policy_and_verification"]["accepted_incorrect"]["k"] == 1
    assert gates["gates"]["policy_and_verification"]["accepted_incorrect_ids"] == ["case-1/wrong"]
    assert gates["gates"]["policy_and_verification"]["rejected_correct"]["k"] == 0

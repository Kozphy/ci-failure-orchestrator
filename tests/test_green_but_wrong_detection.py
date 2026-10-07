import tempfile
from pathlib import Path

from _research_factories import committed_case, facts

from research.repair import ACCEPTED, REJECTED, _annotation_issues, p_composed, r_green, run_oracle


def _candidate(case: dict, candidate_id: str) -> dict:
    return next(c for c in case["repair_fixture"]["candidates"] if c["candidate_id"] == candidate_id)


def test_ci_green_acceptance_of_a_fake_fix_is_an_incorrect_acceptance():
    ordered = [facts("skip", "fake_fix", policy="REJECT", verified=False)]
    decision = r_green("R-GREEN-1", "case-1", ordered, 1)
    assert decision.decision == ACCEPTED
    assert decision.incorrect_acceptance is True


def test_policy_gate_rejects_the_same_fake_fix():
    ordered = [facts("skip", "fake_fix", policy="REJECT", verified=False)]
    decision = p_composed("P-composed", "case-1", ordered, 3)
    assert decision.decision == REJECTED and decision.reason == "policy_rejected"
    assert decision.incorrect_acceptance is False


def test_green_and_verified_but_semantically_wrong_is_still_wrong():
    ordered = [facts("special-case", "semantically_wrong", oracle=False)]
    decision = p_composed("P-composed", "case-1", ordered, 3)
    assert decision.decision == ACCEPTED
    assert decision.incorrect_acceptance is True


def test_correct_label_that_fails_the_oracle_is_flagged_not_counted_correct():
    fact = facts("claimed-correct", "correct", oracle=False)
    assert fact.correct is False
    assert "correct_candidate_fails_oracle" in _annotation_issues("correct", True, False)


def test_hidden_oracle_rejects_skipped_tests_and_special_cases():
    case = committed_case("dev-repair-addition")
    fixture = case["repair_fixture"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = run_oracle(fixture, _candidate(case, "correct")["edits"], root / "good", timeout=120)
        skip = run_oracle(fixture, _candidate(case, "skip-test")["edits"], root / "skip", timeout=120)
        special = run_oracle(fixture, _candidate(case, "special-case")["edits"], root / "special", timeout=120)
        base = run_oracle(fixture, [], root / "base", timeout=120)
    assert good.passed is True, good.detail
    assert skip.passed is False, skip.detail
    assert special.passed is False, special.detail
    assert base.passed is False, base.detail

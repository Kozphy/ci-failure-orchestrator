from _research_factories import committed_case

from research.dataset import Dataset, failure_signature, find_duplicates, validate_dataset


def _renamed(case: dict, case_id: str, uri_suffix: str) -> dict:
    out = dict(case, case_id=case_id)
    out["provenance"] = dict(case["provenance"], source_uri=case["provenance"]["source_uri"] + uri_suffix)
    return out


def test_exact_duplicate_within_a_split_is_an_error():
    case = committed_case("dev-bench-class-003")
    twin = _renamed(case, "dev-bench-class-003-twin", "#twin")
    report = validate_dataset(Dataset({"development": (case, twin), "test": (), "holdout": ()}), require_lock=False)
    assert any("exact duplicate within split" in e for e in report.errors)


def test_numbers_and_hashes_are_normalised_before_comparison():
    case = committed_case("dev-bench-class-003")
    other = _renamed(case, "x", "#x")
    other["observed_failures"] = [dict(case["observed_failures"][0])]
    other["observed_failures"][0]["log_excerpt"] = case["observed_failures"][0]["log_excerpt"] + " at 0xdeadbeef1 line 42"
    base = failure_signature(case)
    assert failure_signature(other).startswith(base)


def test_near_duplicate_across_splits_is_leakage():
    case = committed_case("dev-bench-class-003")
    near = _renamed(case, "test-near", "#near")
    near["split"] = "test"
    words = " ".join(f"word{chr(97 + i % 26)}{chr(97 + i // 26)}" for i in range(40))
    case["observed_failures"] = [dict(case["observed_failures"][0], log_excerpt=words)]
    near["observed_failures"] = [dict(case["observed_failures"][0], log_excerpt=words + " extra")]
    findings = find_duplicates([("development", case), ("test", near)])
    assert findings and findings[0].kind == "near"
    report = validate_dataset(Dataset({"development": (case,), "test": (near,), "holdout": ()}), require_lock=False)
    assert any("cross-split near-duplicate leakage" in e for e in report.errors)


def test_different_repair_fixtures_are_not_duplicates():
    a = committed_case("dev-repair-addition")
    b = committed_case("dev-repair-greeting")
    b["observed_failures"] = a["observed_failures"]
    b["failure_category"] = a["failure_category"]
    assert find_duplicates([("development", a), ("development", b)]) == []

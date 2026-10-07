from _research_factories import committed_case

from research.dataset import Dataset, load_dataset, read_lock, validate_dataset


def _with(dataset: Dataset, split: str, case: dict) -> Dataset:
    splits = dict(dataset.splits)
    splits[split] = (*splits[split], case)
    return Dataset(splits)


def test_committed_dataset_matches_its_lock():
    report = validate_dataset(load_dataset(), lock=read_lock(), require_lock=True)
    assert report.ok, report.errors
    assert report.counts["holdout"] == 0


def test_missing_lock_fails_when_required():
    report = validate_dataset(load_dataset(), lock=None, require_lock=True)
    assert any("lock" in e for e in report.errors)


def test_same_source_in_two_splits_is_leakage():
    dataset = load_dataset()
    leaked = committed_case("dev-bench-class-003")
    leaked["case_id"] = "test-leaked-copy"
    leaked["split"] = "test"
    report = validate_dataset(_with(dataset, "test", leaked), require_lock=False)
    assert any("cross-split leakage" in e for e in report.errors)


def test_editing_a_frozen_case_breaks_the_lock():
    dataset = load_dataset()
    splits = dict(dataset.splits)
    first, *rest = splits["test"]
    edited = dict(first, failure_category="other" if first["failure_category"] != "other" else "dependency")
    splits["test"] = (edited, *rest)
    report = validate_dataset(Dataset(splits), lock=read_lock(), require_lock=True)
    assert any("test: hash differs" in e for e in report.errors)


def test_expected_repair_in_diagnosis_inputs_is_hindsight_leakage():
    case = committed_case("dev-bench-class-003")
    case["ground_truth"]["expected_repair"] = "pin missingpkg to 1.2.3 in requirements.txt"
    case["observed_failures"][0]["log_excerpt"] += "\nhint: pin missingpkg to 1.2.3 in requirements.txt"
    report = validate_dataset(Dataset({"development": (case,), "test": (), "holdout": ()}), require_lock=False)
    assert any("hindsight leakage" in e for e in report.errors)


def test_case_stored_in_the_wrong_split_is_rejected():
    case = committed_case("dev-bench-class-003")
    report = validate_dataset(Dataset({"development": (), "test": (case,), "holdout": ()}), require_lock=False)
    assert any("declares split" in e for e in report.errors)

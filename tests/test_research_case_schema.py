from _research_factories import committed_case

from research.dataset import Dataset, load_dataset, validate_dataset
from research.schema import CURRENT_SCHEMA_VERSION, validate_case


def test_every_committed_case_matches_the_schema():
    cases = load_dataset().cases()
    assert cases
    for case in cases:
        assert validate_case(case) == [], case["case_id"]
        assert case["schema_version"] == CURRENT_SCHEMA_VERSION


def test_missing_required_field_is_rejected():
    case = committed_case("dev-bench-class-003")
    del case["provenance"]["captured_at"]
    assert any("captured_at" in e for e in validate_case(case))


def test_schema_1_1_cases_need_a_content_digest():
    case = committed_case("dev-bench-class-003")
    del case["provenance"]["content_digest"]
    report = validate_dataset(Dataset({"development": (case,), "test": (), "holdout": ()}), require_lock=False)
    assert any("content_digest" in e for e in report.errors)


def test_unknown_source_type_and_unexpected_field_are_rejected():
    case = committed_case("dev-bench-class-003")
    case["source_type"] = "production"
    case["surprise"] = True
    errors = validate_case(case)
    assert any("source_type" in e for e in errors)
    assert any("surprise" in e for e in errors)


def test_source_and_ground_truth_types_stay_distinct():
    case = committed_case("dev-bench-class-003")
    case["source_type"] = "public_real_world"
    case["provenance"]["source_uri"] = "https://github.com/example/repo/actions/runs/1"
    case["provenance"]["failure_time_cutoff"] = "2026-01-01T00:00:00+00:00"
    report = validate_dataset(Dataset({"development": (case,), "test": (), "holdout": ()}), require_lock=False)
    assert any("cannot use validation_method known_fixture" in e for e in report.errors)


def test_real_world_case_requires_failure_time_cutoff():
    case = committed_case("dev-bench-class-003")
    case["source_type"] = "public_real_world"
    case["ground_truth"]["validation_method"] = "maintainer_confirmed"
    case["provenance"]["source_uri"] = "https://github.com/example/repo/actions/runs/2"
    report = validate_dataset(Dataset({"development": (case,), "test": (), "holdout": ()}), require_lock=False)
    assert any("failure_time_cutoff" in e for e in report.errors)

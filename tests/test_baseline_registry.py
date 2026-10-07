import json

import pytest
from _research_factories import committed_case

from ci_failure_orchestrator.baselines import run_baseline
from research.diagnosis import DIAGNOSIS_SYSTEMS, MODEL_SYSTEMS, diagnose, load_prompt
from research.paths import REGISTRY_PATH
from research.providers import MockProvider, NoneProvider, RecordedProvider, parse_prediction
from research.repair import SYSTEMS_DOC
from research.run import SYSTEM_VERSIONS

ABLATIONS = {"P-composed", "P-no-policy", "P-no-verification", "P-no-retry"}


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_registry_lists_every_baseline_the_runner_can_execute():
    ids = {b["id"] for b in _registry()["baselines"]}
    assert set(DIAGNOSIS_SYSTEMS) <= ids
    assert set(SYSTEMS_DOC) - ABLATIONS <= ids
    assert set(SYSTEM_VERSIONS) == set(DIAGNOSIS_SYSTEMS) | set(SYSTEMS_DOC)


def test_runner_versions_match_the_registry():
    for entry in _registry()["baselines"]:
        if entry["id"] in SYSTEM_VERSIONS and entry["id"] != "P":
            assert SYSTEM_VERSIONS[entry["id"]].startswith(entry["version"]), entry["id"]


def test_model_baselines_use_versioned_prompts():
    for system, prompt in MODEL_SYSTEMS.items():
        text, digest = load_prompt(prompt)
        assert "$failures" in text, system
        assert len(digest) == 64


def test_legacy_corpus_runner_still_fails_closed_for_llm_baselines():
    with pytest.raises(ValueError, match="Unsupported executable baseline"):
        run_baseline("B1", {"stages": [], "cases": []})


def test_none_provider_marks_model_baselines_not_run_instead_of_wrong():
    pred = diagnose("B1", committed_case("dev-bench-class-003"), NoneProvider())
    assert pred.status == "not_run"
    assert pred.class_correct is None


def test_mock_provider_is_never_claim_eligible():
    pred = diagnose("B2", committed_case("dev-bench-class-003"), MockProvider())
    assert pred.status == "ok"
    assert pred.claim_eligible is False


def test_recorded_provider_replays_by_request_digest(tmp_path):
    case = committed_case("dev-bench-class-003")
    probe = diagnose("B1", case, NoneProvider())
    answer = {"predicted_failure_class": "dependency", "predicted_root_cause": "deps", "confidence": "high",
              "evidence": ["ModuleNotFoundError"], "recommended_action": "repair_dependency"}
    path = tmp_path / "rec.jsonl"
    row = {"digest": probe.request_digest, "response": {"status": "ok", "text": json.dumps(answer), "reason": ""}}
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    pred = diagnose("B1", case, RecordedProvider(path))
    assert pred.status == "ok" and pred.class_correct is True and pred.claim_eligible is True


def test_prediction_schema_is_strict_and_confidence_is_ordinal():
    good = {"predicted_failure_class": "dependency", "predicted_root_cause": "deps", "confidence": "high",
            "evidence": [], "recommended_action": "repair_dependency"}
    assert parse_prediction(json.dumps(good), ["deps"]).errors == []
    assert "invalid:confidence" in parse_prediction(json.dumps({**good, "confidence": 0.93}), ["deps"]).errors
    assert "unexpected:notes" in parse_prediction(json.dumps({**good, "notes": "x"}), ["deps"]).errors
    assert "invalid:predicted_root_cause_not_a_stage" in parse_prediction(json.dumps(good), ["build"]).errors
    assert parse_prediction("not json").errors

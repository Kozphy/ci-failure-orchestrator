from datetime import datetime, timezone

import pytest

from research.run import RAW_FILES, ExperimentError, _write_exclusive, run_experiment

CONFIG = {
    "experiment": {"name": "immut", "seed": 1, "bootstrap_resamples": 20},
    "dataset": {"splits": ["development"], "case_ids": ["dev-bench-class-003"]},
    "diagnosis": {"enabled": True, "systems": ["B0", "B3"]},
    "repair": {"enabled": False},
    "model": {"provider": "none"},
}
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


def test_exclusive_write_refuses_to_overwrite(tmp_path):
    target = tmp_path / "metrics.json"
    _write_exclusive(target, "{}")
    with pytest.raises(FileExistsError):
        _write_exclusive(target, '{"changed": true}')
    assert target.read_text(encoding="utf-8") == "{}"


def test_rerunning_the_same_experiment_id_does_not_overwrite_raw_results(tmp_path):
    out = run_experiment(CONFIG, raw_root=tmp_path, now=NOW, log=lambda _msg: None)
    assert sorted(p.name for p in out.iterdir()) == sorted(RAW_FILES)
    before = {name: (out / name).read_bytes() for name in RAW_FILES}
    with pytest.raises(FileExistsError):
        run_experiment(CONFIG, raw_root=tmp_path, now=NOW, log=lambda _msg: None)
    assert {name: (out / name).read_bytes() for name in RAW_FILES} == before


def test_holdout_requires_explicit_confirmation(tmp_path):
    config = {**CONFIG, "dataset": {"splits": ["holdout"], "allow_holdout": True}}
    with pytest.raises(ExperimentError, match="holdout"):
        run_experiment(config, raw_root=tmp_path, now=NOW, log=lambda _msg: None)


def test_real_ci_requirement_is_refused_on_fixtures(tmp_path):
    config = {**CONFIG, "repair": {"enabled": True, "require_real_ci": True, "systems": ["R-GREEN-1"]},
              "dataset": {"splits": ["development"], "case_ids": ["dev-repair-addition"]}}
    with pytest.raises(ExperimentError, match="real CI"):
        run_experiment(config, raw_root=tmp_path, now=NOW, log=lambda _msg: None)
    assert list(tmp_path.iterdir()) == []

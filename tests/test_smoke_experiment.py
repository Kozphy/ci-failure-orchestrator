import json

from research.paths import ROOT
from research.report import write_processed
from research.run import RAW_FILES, load_config, run_experiment


def test_smoke_config_runs_end_to_end_without_credentials(tmp_path):
    config = load_config(ROOT / "research" / "config" / "smoke.yaml")
    assert config["model"]["provider"] == "mock"
    out = run_experiment(config, config_path="research/config/smoke.yaml", raw_root=tmp_path / "raw",
                         log=lambda _msg: None)
    assert sorted(p.name for p in out.iterdir()) == sorted(RAW_FILES)

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["holdout_used"] is False
    assert manifest["model"]["claim_eligible"] is False
    assert manifest["dataset_version"] == "1.0.0"

    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["annotation"]["count"] == 0
    assert metrics["fidelity"]["checked"] == metrics["fidelity"]["agree"] == 1
    assert set(metrics["repair"]) >= {"P", "R-GREEN-1", "P-no-policy"}
    assert metrics["diagnosis"]["B1"]["claim_eligible"] is False

    processed = write_processed(out, tmp_path / "processed")
    for name in ("latest_summary.json", "results_table.csv", "diagnosis_metrics.csv", "repair_metrics.csv",
                 "ablation_results.csv", "error_taxonomy.csv"):
        assert (tmp_path / "processed" / name).is_file(), name
    assert processed

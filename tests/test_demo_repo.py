import importlib.util
import json
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo-repo" / "run_demo.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("ci_doctor_demo_repo", DEMO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_repo_goes_from_red_ci_to_verified_local_repair_with_evidence(tmp_path):
    summary = _load_demo().run_demo(tmp_path / "demo")

    assert summary["ci_before_exit"] != 0
    assert summary["ci_after_exit"] == 0
    # Real CI has not run, so the honest local end state stops short of VERIFIED_FIXED.
    assert summary["remediation_state"] == "POLICY_APPROVED"

    report = json.loads(Path(summary["evidence_json"]).read_text(encoding="utf-8"))
    changed = [f["path"] for f in report["what_changed"]["files_changed"]]
    assert changed == ["releasekit/versions.py"]
    assert report["what_broke"]["failure_class"]
    assert report["tests"]["commands_run"]
    assert report["outcome"]["merged"] is False
    assert report["outcome"]["applied"]["branch"] == summary["branch"]
    assert any("real_ci" in risk or "CI" in risk for risk in report["remaining_risks"])
    assert Path(summary["evidence_markdown"]).read_text(encoding="utf-8").startswith("#")

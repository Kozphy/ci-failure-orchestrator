from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ci_failure_orchestrator.cli import build_parser
from ci_failure_orchestrator.service import FixRepoConfig, run_fix_repo
from ci_failure_orchestrator.service.evidence_report import (
    EVIDENCE_REPORT_JSON,
    EVIDENCE_REPORT_MD,
    EVIDENCE_REPORT_SCHEMA,
    _diffstat,
    build_repair_evidence,
)

BUGGY = "def add(a, b):\n    return a - b\n"
FIX_PATCH = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _fixed_run(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "target"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "calc.py").write_bytes(BUGGY.encode("utf-8"))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    patch = tmp_path / "fix.patch"
    patch.write_bytes(FIX_PATCH.encode("utf-8"))
    artifacts = tmp_path / "artifacts"
    outcome = run_fix_repo(
        FixRepoConfig(
            repo_path=repo,
            verify_commands=[f'"{sys.executable}" -c "import calc; assert calc.add(2, 3) == 5"'],
            patch_file=patch,
            artifacts_root=artifacts,
            verify_timeout=120,
        )
    )
    assert outcome["outcome"] == "APPROVED", outcome
    return repo, artifacts, outcome["run_id"]


def test_fix_repo_writes_an_evidence_report_that_answers_each_question(tmp_path):
    _, artifacts, run_id = _fixed_run(tmp_path)
    fix_dir = artifacts / "runs" / run_id / "fix-repo"
    report = json.loads((fix_dir / EVIDENCE_REPORT_JSON).read_text(encoding="utf-8"))

    assert report["schema"] == EVIDENCE_REPORT_SCHEMA
    assert report["what_changed"]["files_changed"] == [{"path": "calc.py", "added": 1, "removed": 1}]
    assert report["why_it_broke"]["hypothesis_basis"].endswith("not a verified root cause")
    assert report["tests"]["verify_commands"] and "calc.add(2, 3)" in report["tests"]["verify_commands"][0]
    assert report["outcome"]["merged"] is False
    assert report["outcome"]["verified"] is False
    # No regression suite or real CI ran here: both must surface as remaining risks, not passes.
    risks = " ".join(report["remaining_risks"])
    assert "regression suite" in risks
    assert "real CI provider has not confirmed" in risks

    markdown = (fix_dir / EVIDENCE_REPORT_MD).read_text(encoding="utf-8")
    for heading in ("What broke?", "Why did it break?", "What changed?", "Why was this fix selected?",
                    "What tests were run?", "What evidence indicates the fix is safe?", "What risks remain?"):
        assert f"## {heading}" in markdown
    assert markdown.isascii()


def test_fix_repo_report_prints_markdown_or_json_and_rejects_unknown_runs(tmp_path, capsys):
    _, artifacts, run_id = _fixed_run(tmp_path)
    capsys.readouterr()

    assert main(["fix-repo-report", run_id, "--artifacts", str(artifacts)]) == 0
    assert capsys.readouterr().out.startswith(f"# Repair evidence: {run_id}")

    assert main(["fix-repo-report", run_id, "--artifacts", str(artifacts), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == run_id

    assert main(["fix-repo-report", "run-missing", "--artifacts", str(artifacts)]) == 2
    assert json.loads(capsys.readouterr().out)["outcome"] == "ERROR"


def test_apply_refreshes_the_report_with_the_new_branch(tmp_path, capsys):
    _, artifacts, run_id = _fixed_run(tmp_path)
    assert main(["fix-repo-apply", run_id, "--artifacts", str(artifacts), "--branch", "fix/calc"]) == 0
    capsys.readouterr()
    applied = build_repair_evidence(artifacts, run_id)["outcome"]["applied"]
    assert applied["branch"] == "fix/calc"
    saved = json.loads((artifacts / "runs" / run_id / "fix-repo" / EVIDENCE_REPORT_JSON).read_text(encoding="utf-8"))
    assert saved["outcome"]["applied"]["branch"] == "fix/calc"


def test_fix_repo_metrics_measures_a_real_run(tmp_path, capsys):
    _, artifacts, _ = _fixed_run(tmp_path)
    capsys.readouterr()

    assert main(["fix-repo-metrics", "--artifacts", str(artifacts)]) == 0
    operational = json.loads(capsys.readouterr().out)["operational"]

    assert operational["failures_ingested"] == 1
    assert operational["mean_time_to_diagnosis_seconds"] is not None
    assert operational["mean_attempts_per_failure"] == 1.0
    assert operational["mean_compute_seconds_per_failure"] > 0
    assert operational["escalation_rate"] == 0.0
    assert operational["model_cost_per_repair"] is None


def test_report_for_a_run_without_repair_artifacts_says_so(tmp_path):
    (tmp_path / "runs" / "run-empty").mkdir(parents=True)
    report = build_repair_evidence(tmp_path, "run-empty")
    assert report["outcome"]["remediation_state"] == "NO_REPAIR_RECORDED"
    assert report["outcome"]["applied"] is None


def test_diffstat_counts_new_deleted_and_hunk_lines_that_look_like_headers():
    patch = (
        "--- a/src/a.py\n+++ b/src/a.py\n@@ -1,2 +1,1 @@\n--- sql comment removed\n x = 1\n"
        "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+y = 2\n"
        "--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-z = 3\n"
    )
    assert _diffstat(patch) == [
        {"path": "src/a.py", "added": 0, "removed": 1},
        {"path": "new.py", "added": 1, "removed": 0},
        {"path": "old.py", "added": 0, "removed": 1},
    ]

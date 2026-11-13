"""Corpus checksums, fail-closed evidence, and the unlabelled external-case manifest."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# SHA-256 of the git blob bytes (LF). A CRLF working tree must not change these.
CORPUS_SHA256 = {
    "benchmark/ci_failure_corpus.v1.json": "a8e6c2e2ba19574a3e3b9faa4327a58c03be30d11e39b790430da96413dadf22",
    "benchmark/repair_fixture_corpus.v1.json": "0a6f1ff41327c9869faad9aa2ca5e23974d3449f5b88e57f790f050f7604211a",
}
ALLOWED_LICENSES = {"MIT", "Apache-2.0", "BSD-3-Clause"}


def _runner():
    path = ROOT / "scripts" / "run_offline_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_offline_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_corpus_bytes_match_the_recorded_checksums():
    runner = _runner()
    for relative, expected in CORPUS_SHA256.items():
        assert runner.canonical_text_sha256(ROOT / relative) == expected


def test_nonzero_exit_is_not_success():
    verdict = _runner().judge([
        {"name": "baseline_matrix", "exit_code": 1, "output_present": True},
    ])
    assert verdict == {"status": "FAILED", "failed_steps": ["baseline_matrix"]}


def test_missing_or_empty_output_is_not_success():
    verdict = _runner().judge([
        {"name": "rq1", "exit_code": 0, "output_present": False},
    ])
    assert verdict["status"] == "FAILED"
    assert verdict["failed_steps"] == ["rq1"]


def test_external_manifest_is_unlabelled():
    manifest = json.loads((ROOT / "benchmark" / "external_cases.v0.json").read_text(encoding="utf-8"))
    assert manifest["labelled_cases"] == 0
    assert len(manifest["cases"]) == 10
    for case in manifest["cases"]:
        assert case["ground_truth"] is None
        assert case["label_status"] == "pending_independent_review"
        assert case["execution"] == "not_run"
        assert case["license_spdx"] in ALLOWED_LICENSES
        assert case["workflow_run"].startswith("https://github.com/")
        assert len(case["head_sha"]) == 40


def test_markdown_names_synthetic_evidence():
    text = _runner().render_markdown({
        "status": "FAILED",
        "git_commit": "abc",
        "python": "3.12.0",
        "platform": "test",
        "failed_steps": ["rq1"],
        "steps": [{"name": "rq1", "exit_code": 0, "output_present": False}],
        "measurements": {"evidence_class": "synthetic_fixture", "independently_labelled_cases": 0},
    })
    assert "synthetic" in text
    assert "not production" in text
    assert "FAILED" in text


def test_offline_runner_writes_a_passing_envelope(tmp_path: Path):
    runner = _runner()
    evidence = runner.build_evidence(ROOT, tmp_path)
    assert evidence["status"] == "PASSED"
    assert evidence["failed_steps"] == []
    assert evidence["measurements"]["independently_labelled_cases"] == 0
    assert evidence["measurements"]["evidence_class"] == "synthetic_fixture"
    assert {row["path"]: row["sha256"] for row in evidence["corpora"]} == CORPUS_SHA256
    for step in evidence["steps"]:
        assert step["exit_code"] == 0
        assert step["output_present"] is True
        assert step["output_sha256"]

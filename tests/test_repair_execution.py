from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ci_failure_orchestrator.patch_sandbox import WorktreePatchVerifier
from ci_failure_orchestrator.provider_adapters import ProviderRun
from ci_failure_orchestrator.repair_execution import (
    RepairExecutionPipeline,
    extract_unified_diff,
    write_execution_evidence,
)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=path, check=True, capture_output=True)
    (path / "hello.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)


def _provider(stdout: str, returncode: int = 0) -> ProviderRun:
    return ProviderRun(
        provider="codex",
        returncode=returncode,
        stdout=stdout,
        stderr="",
        latency_ms=12.5,
        command=("fake",),
        sandbox="/tmp/fake",
    )


def test_extracts_diff_from_markdown() -> None:
    text = "Here is the fix:\n```diff\ndiff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-a\n+b\n```\nDone"
    patch = extract_unified_diff(text)
    assert patch.startswith("diff --git a/a.txt b/a.txt")
    assert "Done" not in patch


def test_pipeline_verifies_patch_and_preserves_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    
    # Create a proper patch by making changes in a temp branch
    subprocess.run(["git", "checkout", "-b", "temp"], cwd=repo, check=True, capture_output=True)
    (repo / "hello.txt").write_text("world\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "change"], cwd=repo, check=True, capture_output=True)
    patch_result = subprocess.run(["git", "format-patch", "--stdout", "HEAD~1"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "-"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-D", "temp"], cwd=repo, check=True, capture_output=True)
    
    # Extract just the diff part from the format-patch output
    patch_lines = []
    in_diff = False
    for line in patch_result.stdout.splitlines():
        if line.startswith("diff --git"):
            in_diff = True
        if in_diff:
            patch_lines.append(line)
    
    patch = "\n".join(patch_lines)
    verifier = WorktreePatchVerifier(commands=(("content-check", ("python", "-c", "from pathlib import Path; assert Path('hello.txt').read_text() == 'world\\n'")),))
    evaluation, evidence = RepairExecutionPipeline(verifier).run(_provider(patch), repo_path=repo)
    assert evaluation.passed is True
    assert evidence.patch_found is True
    assert evidence.verification_passed is True
    assert evidence.changed_files == ("hello.txt",)
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "hello\n"


def test_no_patch_fails_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    verifier = WorktreePatchVerifier(commands=(("noop", ("python", "-c", "pass")),))
    evaluation, evidence = RepairExecutionPipeline(verifier).run(_provider("I suggest changing the file."), repo_path=repo)
    assert evaluation.passed is False
    assert evaluation.score == 0.0
    assert "no_patch" in evaluation.reasons
    assert evidence.patch_found is False


def test_writes_json_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    verifier = WorktreePatchVerifier(commands=(("noop", ("python", "-c", "pass")),))
    _, evidence = RepairExecutionPipeline(verifier).run(_provider("no patch"), repo_path=repo)
    target = tmp_path / "evidence.json"
    write_execution_evidence(target, [evidence])
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data[0]["provider"] == "codex"
    assert data[0]["patch_found"] is False

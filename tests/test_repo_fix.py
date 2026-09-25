from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ci_failure_orchestrator.cli import build_parser
from ci_failure_orchestrator.foundation import apply_reviewer_decision, verify_run_consistency
from ci_failure_orchestrator.foundation.persistence import FileAuditStore
from ci_failure_orchestrator.repo_fix import (
    FixRepoConfig,
    PatchFileSource,
    apply_fix,
    extract_patch,
    parse_patch_files,
    run_fix_repo,
    split_command,
)

BUGGY = "def add(a, b):\n    return a - b\n"
FIX_PATCH = (
    "diff --git a/calc.py b/calc.py\n"
    "--- a/calc.py\n"
    "+++ b/calc.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n"
    "-    return a - b\n"
    "+    return a + b\n"
)
WRONG_PATCH = FIX_PATCH.replace("a + b", "a * b")
STALE_PATCH = FIX_PATCH.replace(" def add(a, b):", " def plus(a, b):")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "target"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def _verify_cmd(module: str = "calc", expr: str = "calc.add(2, 3) == 5") -> str:
    return f'"{sys.executable}" -c "import {module}; assert {expr}"'


def _write_patch(tmp_path: Path, text: str, name: str = "fix.patch") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def _config(repo: Path, tmp_path: Path, **overrides) -> FixRepoConfig:
    values = {
        "repo_path": repo,
        "verify_commands": [_verify_cmd()],
        "artifacts_root": tmp_path / "artifacts",
        "verify_timeout": 120,
    }
    values.update(overrides)
    return FixRepoConfig(**values)


def test_extract_patch_from_fenced_llm_output() -> None:
    text = f"Here is the fix:\r\n```diff\r\n{FIX_PATCH.replace(chr(10), chr(13) + chr(10))}```\r\nRationale: wrong operator\r\n"
    patch = extract_patch(text)
    assert patch == FIX_PATCH
    assert "\r" not in patch


def test_extract_patch_unfenced_trims_trailing_prose() -> None:
    patch = extract_patch("Some intro\n" + FIX_PATCH + "\nRationale: wrong operator\n")
    assert patch == FIX_PATCH
    assert extract_patch("no diff here") == ""


def test_parse_patch_files_handles_new_deleted_and_hunk_dashes() -> None:
    patch = (
        "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1,2 +1,1 @@\n"
        "--- sql comment removed\n x = 1\n"
        "diff --git a/new.py b/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+y = 2\n"
        "diff --git a/old.py b/old.py\ndeleted file mode 100644\n--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-z = 3\n"
    )
    assert parse_patch_files(patch) == ("src/a.py", "new.py", "old.py")


def test_split_command_keeps_windows_paths_and_quotes() -> None:
    argv = split_command(r'"C:\Program Files\tool.exe" -c "import x; y"')
    assert argv == (r"C:\Program Files\tool.exe", "-c", "import x; y")


def test_patch_file_source_reads_utf16_powershell_output(tmp_path: Path) -> None:
    path = tmp_path / "ps.patch"
    path.write_bytes(b"\xff\xfe" + FIX_PATCH.replace("\n", "\r\n").encode("utf-16-le"))
    assert extract_patch(PatchFileSource(path).generate("", 1).text) == FIX_PATCH


def test_patch_file_is_verified_approved_and_applied_to_new_branch(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"calc.py": BUGGY})
    start_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()

    outcome = run_fix_repo(_config(repo, tmp_path, patch_file=_write_patch(tmp_path, FIX_PATCH)))

    assert outcome["outcome"] == "APPROVED", outcome
    assert outcome["files_changed"] == ["calc.py"]
    assert outcome["primary_workspace_mutated"] is False
    assert (repo / "calc.py").read_bytes().decode() == BUGGY
    assert _git(repo, "status", "--porcelain").strip() == ""

    artifacts = tmp_path / "artifacts"
    run_id = outcome["run_id"]
    applied = apply_fix(artifacts, run_id)
    assert applied.status == "APPLIED", applied
    assert _git(repo, "show", f"{applied.branch}:calc.py").replace("\r\n", "\n") == BUGGY.replace("a - b", "a + b")
    assert (repo / "calc.py").read_bytes().decode() == BUGGY
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == start_branch
    assert f"run {run_id}" in _git(repo, "log", "-1", "--format=%B", applied.branch)

    events = [e.event_type for e in FileAuditStore(artifacts).read_events(run_id)]
    assert events[-1] == "TARGET_PATCH_APPLIED"
    assert verify_run_consistency(artifacts_root=artifacts, run_id=run_id).valid

    again = apply_fix(artifacts, run_id, branch="another-branch")
    assert again.status == "BLOCKED"
    assert "already applied" in again.message


def test_apply_leaves_unrelated_local_changes_alone(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"calc.py": BUGGY, "notes.txt": "draft\n"})
    outcome = run_fix_repo(_config(repo, tmp_path, patch_file=_write_patch(tmp_path, FIX_PATCH)))
    assert outcome["outcome"] == "APPROVED", outcome

    (repo / "notes.txt").write_bytes(b"local edit in progress\n")
    applied = apply_fix(tmp_path / "artifacts", outcome["run_id"])

    assert applied.status == "APPLIED", applied
    assert (repo / "notes.txt").read_bytes() == b"local edit in progress\n"


def test_patch_that_does_not_fix_the_failure_is_rejected(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"calc.py": BUGGY})
    outcome = run_fix_repo(_config(repo, tmp_path, patch_file=_write_patch(tmp_path, WRONG_PATCH)))

    assert outcome["outcome"] == "FAILED", outcome
    assert outcome["patch_path"] is None
    assert any("verification command failed" in f["reason"] for f in outcome["feedback"])
    assert apply_fix(tmp_path / "artifacts", outcome["run_id"]).status == "BLOCKED"


def test_no_failure_when_verification_already_passes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"calc.py": BUGGY.replace("a - b", "a + b")})
    outcome = run_fix_repo(_config(repo, tmp_path, patch_file=_write_patch(tmp_path, FIX_PATCH)))
    assert outcome["outcome"] == "NO_FAILURE"


def test_provider_gets_feedback_and_retries_until_verified(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"calc.py": BUGGY})
    provider = tmp_path / "fake_provider.py"
    provider.write_text(
        "import sys\n"
        "prompt = sys.stdin.read()\n"
        f"good = {FIX_PATCH!r}\n"
        f"stale = {STALE_PATCH!r}\n"
        "assert 'def add(a, b):' in prompt, 'file contents missing from prompt'\n"
        "patch = good if 'Previous attempt 1 failed' in prompt else stale\n"
        "print('```diff\\n' + patch + '```\\nRationale: use addition')\n",
        encoding="utf-8",
    )
    outcome = run_fix_repo(
        _config(repo, tmp_path, provider_cmd=f'"{sys.executable}" "{provider}"', provider_timeout=60)
    )

    assert outcome["outcome"] == "APPROVED", outcome
    assert outcome["attempts"] == 2
    assert outcome["feedback"][0]["reason"] == "patch_check_failed"
    fix_dir = tmp_path / "artifacts" / "runs" / outcome["run_id"] / "fix-repo"
    assert (fix_dir / "attempt-002-prompt.txt").is_file()
    assert "Rationale: use addition" in (fix_dir / "attempt-002-response.txt").read_text(encoding="utf-8")


def test_escalated_change_needs_human_approval_before_apply(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"auth/login.py": BUGGY})
    patch = FIX_PATCH.replace("calc.py", "auth/login.py")
    outcome = run_fix_repo(
        _config(
            repo,
            tmp_path,
            patch_file=_write_patch(tmp_path, patch),
            verify_commands=[_verify_cmd("auth.login", "auth.login.add(2, 3) == 5")],
        )
    )
    assert outcome["outcome"] == "AWAITING_HUMAN", outcome

    artifacts = tmp_path / "artifacts"
    run_id = outcome["run_id"]
    blocked = apply_fix(artifacts, run_id)
    assert blocked.status == "BLOCKED"
    assert "AWAITING_HUMAN" in blocked.message

    decision = apply_reviewer_decision(artifacts, run_id, action="APPROVE", reviewer_id="alice")
    assert decision.workflow_status_after == "APPROVED"

    applied = apply_fix(artifacts, run_id)
    assert applied.status == "APPLIED", applied
    assert "human APPROVE" in _git(repo, "log", "-1", "--format=%B", applied.branch)


def test_cli_fix_repo_and_apply(tmp_path: Path, capsys) -> None:
    repo = _make_repo(tmp_path, {"calc.py": BUGGY})
    patch = _write_patch(tmp_path, FIX_PATCH)
    artifacts = tmp_path / "artifacts"

    args = build_parser().parse_args(
        [
            "fix-repo",
            "--repo-path", str(repo),
            "--verify", _verify_cmd(),
            "--patch-file", str(patch),
            "--artifacts", str(artifacts),
        ]
    )
    assert args.func(args) == 0
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["outcome"] == "APPROVED"

    args = build_parser().parse_args(
        ["fix-repo-apply", outcome["run_id"], "--artifacts", str(artifacts), "--branch", "fix/calc"]
    )
    assert args.func(args) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["branch"] == "fix/calc"
    assert _git(repo, "rev-parse", "--verify", "refs/heads/fix/calc").strip() == applied["commit"]

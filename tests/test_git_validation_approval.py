from pathlib import Path
import subprocess

from ci_failure_orchestrator.approval import ApprovalContext, ApprovalDecision, HumanApprovalGate
from ci_failure_orchestrator.git_validation import GitPatchValidator


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_git_patch_validator_accepts_bounded_diff(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@example.com")
    _git(repo, "config", "user.name", "CI")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")

    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    result = GitPatchValidator(max_changed_files=2, max_diff_lines=20).validate(repo)

    assert result.valid is True
    assert result.changed_files == ("app.py",)


def test_git_patch_validator_rejects_empty_diff(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    result = GitPatchValidator().validate(repo)
    assert result.valid is False
    assert result.reason == "repair produced no git diff"


def test_human_approval_required_for_high_risk_paths():
    gate = HumanApprovalGate()
    context = ApprovalContext(
        policy_decision="release",
        evaluation_score=0.99,
        regression_free=True,
        changed_files=(".github/workflows/ci.yml",),
    )
    assert gate.evaluate(context).decision is ApprovalDecision.REQUIRED
    assert gate.evaluate(context, human_approved=True).decision is ApprovalDecision.APPROVED


def test_low_risk_high_score_repair_can_pass_automated_gate():
    gate = HumanApprovalGate()
    context = ApprovalContext(
        policy_decision="release",
        evaluation_score=0.99,
        regression_free=True,
        changed_files=("ci_failure_orchestrator/classifier.py",),
    )
    assert gate.evaluate(context).decision is ApprovalDecision.APPROVED

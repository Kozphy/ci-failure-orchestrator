"""Stage 3: environment / dependency / unknown failures and low confidence escalate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ci_failure_orchestrator.foundation.classifier import FailureClassifier
from ci_failure_orchestrator.foundation.models import (
    EvaluationResult,
    FailureClassification,
    FailureEvent,
    RepairProposal,
)
from ci_failure_orchestrator.foundation.policy import (
    RULE_FAILURE_CATEGORY,
    RULE_LOW_CONFIDENCE,
    PolicyConfig,
    PolicyOutcome,
    StaticPolicyEngine,
    build_policy_context,
)
from ci_failure_orchestrator.patch_sandbox import VerificationStep
from ci_failure_orchestrator.service import FixRepoConfig, TaskStore, apply_fix, run_fix_repo
from ci_failure_orchestrator.service.environment import detect_environment_failure
from ci_failure_orchestrator.service.session import VerifyCommand

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
GH_TOKEN = "ghp_" + "Q1w2E3r4" * 5


# --- Policy ------------------------------------------------------------------------------


def _evaluation(*, passed: bool) -> EvaluationResult:
    return EvaluationResult(
        run_id="r",
        passed=passed,
        patch_applied=True,
        target_verification_passed=passed,
        regressions_detected=False,
        forbidden_changes_detected=False,
        checks=(),
        evidence=(),
    )


def _decide(category: str | None, confidence: float = 0.9, *files: str):
    proposal = RepairProposal(
        proposal_id="p",
        run_id="r",
        files_changed=files or ("src/calc.py",),
        patch="--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1 +1 @@\n-a\n+b\n",
        rationale="fix",
        expected_effect="tests pass",
        verification_plan=("pytest",),
    )
    evaluation = _evaluation(passed=True)
    classification = (
        None
        if category is None
        else FailureClassification(run_id="r", category=category, evidence=(), confidence=confidence, uncertainty="")
    )
    context = build_policy_context(proposal=proposal, evaluation=evaluation, classification=classification)
    return StaticPolicyEngine().evaluate(context)


@pytest.mark.parametrize(
    "category", ["dependency_failure", "infrastructure_failure", "network_failure", "unknown"]
)
def test_environment_and_unknown_categories_escalate_small_source_patch(category: str) -> None:
    decision = _decide(category)
    assert decision.outcome is PolicyOutcome.ESCALATE
    assert RULE_FAILURE_CATEGORY in decision.matched_rules
    assert f"failure_category:{category}" in decision.reasons
    assert f"failure_category={category}" in decision.evidence


@pytest.mark.parametrize("category", ["test_failure", "lint_failure", "type_failure"])
def test_code_failures_with_confident_classification_still_auto_approve(category: str) -> None:
    decision = _decide(category, 0.9)
    assert decision.outcome is PolicyOutcome.APPROVE, decision.explain()


def test_low_confidence_escalates() -> None:
    decision = _decide("test_failure", 0.5)
    assert decision.outcome is PolicyOutcome.ESCALATE
    assert RULE_LOW_CONFIDENCE in decision.matched_rules
    assert "low_classification_confidence" in decision.reasons


def test_missing_classification_escalates() -> None:
    decision = _decide(None)
    assert decision.outcome is PolicyOutcome.ESCALATE
    assert "classification_missing" in decision.reasons


def test_failed_evaluation_still_rejects_before_classification_rules() -> None:
    proposal = RepairProposal("p", "r", ("src/calc.py",), "x", "r", "e", ())
    evaluation = _evaluation(passed=False)
    classification = FailureClassification("r", "dependency_failure", (), 0.9, "")
    context = build_policy_context(proposal=proposal, evaluation=evaluation, classification=classification)
    assert StaticPolicyEngine().evaluate(context).outcome is PolicyOutcome.REJECT


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_confidence_threshold_is_validated(value: float) -> None:
    with pytest.raises(ValueError):
        PolicyConfig(min_classification_confidence=value)


# --- Classifier ------------------------------------------------------------------------


def _event(**fields) -> FailureEvent:
    base = {"workflow": "ci", "job": "test", "failed_step": "Run pytest", "message": "", "log_excerpt": ""}
    base.update(fields)
    return FailureEvent.from_dict(base, run_id="r")


def test_missing_package_in_a_test_job_is_a_dependency_failure() -> None:
    result = FailureClassifier().classify(_event(message="ModuleNotFoundError: No module named 'requests'"))
    assert result.category == "dependency_failure"
    assert "actions=unit_test_failure" in result.evidence


def test_network_error_in_log_outranks_job_name() -> None:
    result = FailureClassifier().classify(
        _event(message="tests failed", log_excerpt="urllib3: connection reset by peer")
    )
    assert result.category == "network_failure"


def test_plain_assertion_in_test_job_stays_a_test_failure() -> None:
    result = FailureClassifier().classify(_event(message="AssertionError: expected 5 got -1"))
    assert result.category == "test_failure"


# --- End to end: fix-repo ---------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "calc.py").write_bytes(BUGGY.encode("utf-8"))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def _py(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


def _config(repo: Path, tmp_path: Path, **overrides) -> FixRepoConfig:
    patch = tmp_path / "fix.patch"
    patch.write_bytes(FIX_PATCH.encode("utf-8"))
    values = {
        "repo_path": repo,
        "verify_commands": [_py("import calc; assert calc.add(2, 3) == 5")],
        "artifacts_root": tmp_path / "artifacts",
        "verify_timeout": 120,
        "patch_file": patch,
    }
    values.update(overrides)
    return FixRepoConfig(**values)


def test_dependency_failure_with_source_only_patch_awaits_human(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    failure = {
        "workflow": "ci",
        "job": "test",
        "failed_step": "Run pytest",
        "message": "ModuleNotFoundError: No module named 'missingpkg'",
        "log_excerpt": "ERROR: No matching distribution found for missingpkg",
    }
    outcome = run_fix_repo(_config(repo, tmp_path, failure=failure))

    assert outcome["outcome"] == "AWAITING_HUMAN", outcome
    assert outcome["technical_status"] == "PASS"
    assert outcome["policy_outcome"] == "ESCALATE"
    assert RULE_FAILURE_CATEGORY in outcome["policy_rules"]
    assert outcome["files_changed"] == ["calc.py"]
    run_root = tmp_path / "artifacts" / "runs" / outcome["run_id"]
    decision = json.loads((run_root / "policy" / "policy-decision.json").read_text(encoding="utf-8"))
    assert "failure_category:dependency_failure" in decision["reasons"]


def _spy_provider(tmp_path: Path) -> tuple[str, Path]:
    marker = tmp_path / "provider-called"
    script = tmp_path / "spy_provider.py"
    script.write_text(
        f"import pathlib, sys\nsys.stdin.read()\npathlib.Path({str(marker)!r}).write_text('x')\n"
        f"print('```diff\\n' + {FIX_PATCH!r} + '```')\n",
        encoding="utf-8",
    )
    return f'"{sys.executable}" "{script}"', marker


@pytest.mark.parametrize(
    ("verify", "kind"),
    [
        (_py("import missingpkg_stage3"), "missing_dependency"),
        ("definitely-not-a-command-stage3 --version", "missing_command"),
        (_py("import sys; sys.exit('Could not resolve host: pypi.org')"), "network"),
    ],
)
def test_environment_failure_at_reproduce_escalates_without_calling_provider(
    verify: str, kind: str, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path)
    provider_cmd, marker = _spy_provider(tmp_path)
    outcome = run_fix_repo(
        _config(repo, tmp_path, verify_commands=[verify], patch_file=None, provider_cmd=provider_cmd)
    )

    assert outcome["outcome"] == "AWAITING_HUMAN", outcome
    assert outcome["provider_called"] is False
    assert outcome["attempts"] == 0
    assert outcome["stop_reason"] == f"environment_failure:{kind}"
    assert not marker.exists()

    run_root = tmp_path / "artifacts" / "runs" / outcome["run_id"]
    record = json.loads((run_root / "fix-repo" / "environment-escalation.json").read_text(encoding="utf-8"))
    assert record["finding"]["kind"] == kind
    assert record["stage"] == "reproduce"
    assert not (run_root / "state.json").exists()
    assert not list(run_root.rglob("*prompt*"))

    (run,) = TaskStore(tmp_path / "artifacts").runs(outcome["task_id"])
    assert run["workflow_status"] == "AWAITING_HUMAN"
    assert run["attempts"] == 0

    applied = apply_fix(tmp_path / "artifacts", outcome["run_id"])
    assert applied.status != "APPLIED"


def test_missing_repo_module_is_not_an_environment_failure(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    outcome = run_fix_repo(
        _config(repo, tmp_path, verify_commands=[_py("import calc.sub")])
    )
    assert outcome.get("provider_called") is not False
    assert outcome["attempts"] >= 1


def test_environment_escalation_reuses_task_and_redacts_evidence(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    first = run_fix_repo(_config(repo, tmp_path, verify_commands=[_py("import missingpkg_stage3")]))
    verify = _py(f"import sys; sys.exit('Could not resolve host with token {GH_TOKEN}')")
    second = run_fix_repo(_config(repo, tmp_path, verify_commands=[verify], task_id=first["task_id"]))
    assert second["task_id"] == first["task_id"]
    assert len(TaskStore(tmp_path / "artifacts").runs(first["task_id"])) == 2
    assert GH_TOKEN not in json.dumps(second)
    for path in (tmp_path / "artifacts").rglob("*"):
        if path.is_file():
            assert GH_TOKEN not in path.read_text(encoding="utf-8")


# --- Detector unit tests ---------------------------------------------------------------

COMMANDS = (VerifyCommand("step-1", "pytest -q", ("pytest", "-q")),)


def _step(stderr: str, returncode: int = 1, stdout: str = "") -> VerificationStep:
    return VerificationStep("step-1", returncode, stdout, stderr, 1.0)


@pytest.mark.parametrize(
    ("stderr", "returncode", "kind"),
    [
        ("command_not_runnable: [WinError 2]", 127, "missing_command"),
        ("bash: tox: command not found", 127, "missing_command"),
        ("'npm' is not recognized as an internal or external command", 1, "missing_command"),
        ("ERROR: No matching distribution found for foo==9.9", 1, "dependency_resolution"),
        ("npm ERR! code ERESOLVE", 1, "dependency_resolution"),
        ("Failed to establish a new connection: [Errno 111]", 1, "network"),
        ("OSError: [Errno 28] No space left on device", 1, "resource_exhaustion"),
        ("", 137, "resource_exhaustion"),
        ("ModuleNotFoundError: No module named 'yaml'", 1, "missing_dependency"),
        ("Error: Cannot find module 'express'", 1, "missing_dependency"),
        ("Error: Cannot find module '@scope/pkg/lib'", 1, "missing_dependency"),
    ],
)
def test_detector_kinds(stderr: str, returncode: int, kind: str) -> None:
    finding = detect_environment_failure((_step(stderr, returncode),), COMMANDS, ("calc.py",))
    assert finding is not None
    assert finding.kind == kind
    assert finding.command == "pytest -q"


@pytest.mark.parametrize(
    "stderr",
    [
        "AssertionError: assert 6 == 5",
        "ModuleNotFoundError: No module named 'calc.sub'",
        "ModuleNotFoundError: No module named 'pkg.helpers'",
        "Error: Cannot find module './local'",
        "ConnectionRefusedError: [Errno 111] Connection refused",
    ],
)
def test_detector_ignores_code_failures(stderr: str) -> None:
    tracked = ("calc.py", "src/pkg/helpers.py")
    assert detect_environment_failure((_step(stderr),), COMMANDS, tracked) is None


def test_detector_ignores_passing_steps_and_sanitizes_evidence() -> None:
    passing = _step("No space left on device", returncode=0)
    assert detect_environment_failure((passing,), COMMANDS, ()) is None
    noisy = _step(f"\x1b[31mCould not resolve host\x1b[0m token={GH_TOKEN}")
    finding = detect_environment_failure((noisy,), COMMANDS, ())
    assert finding is not None
    assert "\x1b" not in finding.evidence
    assert GH_TOKEN not in finding.evidence

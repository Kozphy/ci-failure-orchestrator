"""Regression tests for defects found in the Phase 0 assessment (docs/architecture/current-state.md §7.1)."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from ci_failure_orchestrator.foundation import AgentExecutionFoundation, FailureEvent
from ci_failure_orchestrator.foundation.classifier import FailureClassifier
from ci_failure_orchestrator.foundation.escalation import EscalationReasonCode, map_reason_codes
from ci_failure_orchestrator.foundation.models import (
    CheckStatus,
    EvaluationCheck,
    EvaluationResult,
    FailureClassification,
    RepairProposal,
    SandboxResult,
    new_id,
)
from ci_failure_orchestrator.foundation.observability.metrics import InMemoryMetricsRecorder
from ci_failure_orchestrator.foundation.persistence import PersistenceError
from ci_failure_orchestrator.foundation.policy import (
    RULE_BROAD_SCOPE,
    RULE_ESCALATION_PATH,
    RULE_INFRA_OR_MIGRATION,
    RULE_SECURITY_SENSITIVE,
    PolicyOutcome,
    StaticPolicyEngine,
    build_policy_context,
)
from ci_failure_orchestrator.foundation.retry import RetryBudget
from ci_failure_orchestrator.patch_sandbox import WorktreePatchVerifier
from ci_failure_orchestrator.repo_fix import FixRepoConfig, run_fix_repo

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


def _event() -> FailureEvent:
    return FailureEvent(
        event_id=new_id("evt"),
        run_id=new_id("run"),
        source="synthetic",
        workflow="ci",
        job="test",
        failed_step="pytest",
        message="AssertionError: expected True",
        changed_paths=("src/app.py",),
        log_excerpt="FAILED tests/test_app.py::test_x",
        exit_code=1,
    )


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


def test_persistence_failure_is_reported_as_persistence_error(tmp_path: Path, monkeypatch) -> None:
    metrics = InMemoryMetricsRecorder()
    foundation = AgentExecutionFoundation(artifacts_root=tmp_path, metrics=metrics)
    assert foundation.persistence is not None

    def fail(kind: str, *args, **kwargs):
        if kind == "plan":
            raise PersistenceError("disk full")
        return original(kind, *args, **kwargs)

    original = foundation.persistence.write_json
    monkeypatch.setattr(foundation.persistence, "write_json", fail)

    result = foundation.run(_event())

    assert result.workflow_status == "PERSISTENCE_ERROR"
    assert result.run.stop_reason == "PERSISTENCE_ERROR:disk full"
    runs = metrics.snapshot()["counters"]["orchestrator_runs_total"]
    assert any("workflow_status=PERSISTENCE_ERROR" in key for key in runs)
    summary = json.loads(
        (tmp_path / "runs" / result.run.run_id / "metrics-summary.json").read_text(encoding="utf-8")
    )
    assert summary["persistence_ok"] is False


class _AlternatingSandbox:
    """Fails every attempt with a different recoverable error so failure fingerprints differ."""

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, proposal: RepairProposal, verification_steps, *, target_should_pass: bool = True) -> SandboxResult:
        self.calls += 1
        error = ("patch_check_failed", "patch_apply_failed", "no_patch_extracted")[(self.calls - 1) % 3]
        return SandboxResult(proposal.run_id, proposal.proposal_id, False, False, (), (), error=error)


class _CountingClassifier(FailureClassifier):
    def __init__(self) -> None:
        self.calls = 0

    def classify(self, event: FailureEvent) -> FailureClassification:
        self.calls += 1
        result = super().classify(event)
        # Any later call would hand back a different, lower-confidence label.
        return result if self.calls == 1 else replace(result, category="docs_failure", confidence=0.99)


def test_classification_stays_fixed_to_the_reported_failure_across_retries() -> None:
    sandbox = _AlternatingSandbox()
    foundation = AgentExecutionFoundation(
        sandbox=sandbox,
        retry_budget=RetryBudget(max_attempts=3, max_no_progress_attempts=3),
    )
    classifier = _CountingClassifier()
    foundation.classifier = classifier

    result = foundation.run(_event())

    assert sandbox.calls == 3
    assert classifier.calls == 1
    assert result.run.classification is not None
    assert result.run.classification.category != "docs_failure"


def _passing_eval() -> EvaluationResult:
    return EvaluationResult(
        run_id="r",
        passed=True,
        patch_applied=True,
        target_verification_passed=True,
        regressions_detected=False,
        forbidden_changes_detected=False,
        checks=(EvaluationCheck("TARGET_TEST_PASSED", CheckStatus.PASSED),),
        evidence=(),
    )


def _decide(path: str):
    proposal = RepairProposal(
        proposal_id=new_id("prop"),
        run_id="r",
        files_changed=(path,),
        patch="--- a/x\n+++ b/x\n@@\n+# fix\n",
        rationale="r",
        expected_effect="e",
        verification_plan=("target_verification",),
    )
    classification = FailureClassification(
        run_id="r", category="test_failure", evidence=(), confidence=0.9, uncertainty="heuristic"
    )
    context = build_policy_context(proposal=proposal, evaluation=_passing_eval(), classification=classification)
    return context, StaticPolicyEngine().evaluate(context)


def test_escalation_path_hit_has_its_own_rule_id() -> None:
    _, decision = _decide("src/infra/settings.py")
    assert decision.outcome is PolicyOutcome.ESCALATE
    assert RULE_ESCALATION_PATH in decision.matched_rules
    assert RULE_SECURITY_SENSITIVE not in decision.matched_rules


def test_infrastructure_change_is_not_labelled_broad_scope() -> None:
    context, decision = _decide("infra/main.tf")
    assert decision.outcome is PolicyOutcome.ESCALATE
    assert decision.matched_rules == (RULE_INFRA_OR_MIGRATION,)
    assert RULE_BROAD_SCOPE not in decision.matched_rules
    codes = map_reason_codes(decision, context.file_categories)
    assert EscalationReasonCode.INFRASTRUCTURE_CHANGE in codes
    assert EscalationReasonCode.BROAD_CHANGE_SCOPE not in codes


def test_failed_provider_output_is_never_verified(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    provider = tmp_path / "crashing_provider.py"
    provider.write_text(
        "import sys\n"
        "sys.stdin.read()\n"
        f"print('```diff\\n' + {FIX_PATCH!r} + '```')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    outcome = run_fix_repo(
        FixRepoConfig(
            repo_path=repo,
            verify_commands=[f'"{sys.executable}" -c "import calc; assert calc.add(2, 3) == 5"'],
            artifacts_root=tmp_path / "artifacts",
            verify_timeout=120,
            provider_cmd=f'"{sys.executable}" "{provider}"',
            provider_timeout=60,
            max_attempts=1,
        )
    )

    assert outcome["outcome"] != "APPROVED", outcome
    assert outcome["patch_path"] is None
    assert [f["reason"] for f in outcome["feedback"]] == ["provider_failed"]


def test_clean_after_apply_reports_files_left_by_verification(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    quiet = WorktreePatchVerifier(commands=[("check", (sys.executable, "-B", "-c", "pass"))])
    noisy = WorktreePatchVerifier(
        commands=[("check", (sys.executable, "-B", "-c", "open('leftover.txt', 'w').write('x')"))]
    )

    clean = quiet.verify(repo_path=repo, patch_text=FIX_PATCH)
    dirty = noisy.verify(repo_path=repo, patch_text=FIX_PATCH)

    assert clean.applied and clean.passed and clean.clean_after_apply is True
    assert dirty.applied and dirty.passed and dirty.clean_after_apply is False

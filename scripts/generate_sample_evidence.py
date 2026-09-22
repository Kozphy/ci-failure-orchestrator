#!/usr/bin/env python3
"""Generate committed sample foundation evidence (synthetic, deterministic).

Produces approve / reject / escalate runs under evidence/sample-runs/ plus
evidence/manifest.json. Not production (E5) evidence.

Usage (from repo root):
  python scripts/generate_sample_evidence.py
  ci-orchestrator foundation-verify <run_id> --artifacts evidence/sample-runs/<label>
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ci_failure_orchestrator.foundation import (
    AgentExecutionFoundation,
    ScriptedProposalFactory,
    apply_reviewer_decision,
)
from ci_failure_orchestrator.foundation.models import (
    CheckStatus,
    EvaluationCheck,
    EvaluationResult,
    FailureEvent,
    RepairProposal,
    SandboxResult,
    ToolResult,
    new_id,
)
from ci_failure_orchestrator.foundation.persistence import inspect_run, verify_run_consistency
from ci_failure_orchestrator.foundation.policy import PolicyOutcome

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
SAMPLE = EVIDENCE / "sample-runs"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _event(run_id: str, changed_paths: tuple[str, ...] = ("src/app.py",)) -> FailureEvent:
    return FailureEvent(
        event_id=new_id("evt"),
        run_id=run_id,
        source="synthetic",
        workflow="ci",
        job="test",
        failed_step="pytest",
        message="AssertionError",
        log_excerpt="FAILED tests/test_app.py::test_login - AssertionError",
        changed_paths=changed_paths,
        exit_code=1,
    )


class _PassEval:
    def evaluate(self, *, proposal, sandbox) -> EvaluationResult:
        return EvaluationResult(
            run_id=proposal.run_id,
            passed=True,
            patch_applied=True,
            target_verification_passed=True,
            regressions_detected=False,
            forbidden_changes_detected=False,
            checks=(
                EvaluationCheck("PATCH_APPLIED", CheckStatus.PASSED),
                EvaluationCheck("TARGET_TEST_PASSED", CheckStatus.PASSED),
            ),
            evidence=("target_verification:PASS",),
        )


class _AllowSandbox:
    def execute(self, proposal, verification_steps, *, target_should_pass: bool = True):
        return SandboxResult(
            run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            success=True,
            patch_applied=True,
            command_results=(ToolResult("test_runner", True, 0, stdout="PASS"),),
            changed_files=proposal.files_changed,
        )


def _reset_label(label: str) -> Path:
    path = SAMPLE / label
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def main() -> int:
    SAMPLE.mkdir(parents=True, exist_ok=True)
    commit = _git_commit()
    entries: list[dict] = []

    # --- 01 APPROVE (low-risk source/test) ---
    art1 = _reset_label("01-approve")
    ws1 = art1 / "workspace"
    (ws1 / "src").mkdir(parents=True)
    (ws1 / "tests").mkdir(parents=True)
    (ws1 / "src" / "app.py").write_text("def login():\n    return False\n", encoding="utf-8")
    (ws1 / "tests" / "test_app.py").write_text(
        "def test_login():\n    assert False\n", encoding="utf-8"
    )
    r1 = AgentExecutionFoundation(
        workspace_root=ws1,
        artifacts_root=art1,
        enable_persistence=True,
        target_pass_schedule=[True],
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p-approve",
                    run_id="sample-approve",
                    files_changed=("src/app.py", "tests/test_app.py"),
                    patch="--- a/src/app.py\n+++ b/src/app.py\n@@\n+# ok\n",
                    rationale="low-risk source/test fix",
                    expected_effect="tests pass",
                    verification_plan=("target_verification",),
                )
            ]
        ),
    ).run(_event("sample-approve"))
    if r1.policy_outcome is not PolicyOutcome.APPROVE:
        raise SystemExit(f"expected APPROVE, got {r1.policy_outcome} / {r1.status}")
    entries.append(
        (
            "01-approve",
            r1,
            art1,
            "Low-risk source/test repair → policy APPROVE (BENCH-POLICY-001 analogue)",
        )
    )

    # --- 02 REJECT (forbidden .git path despite technical PASS) ---
    art2 = _reset_label("02-reject")
    r2 = AgentExecutionFoundation(
        artifacts_root=art2,
        enable_persistence=True,
        sandbox=_AllowSandbox(),
        evaluator=_PassEval(),
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p-reject",
                    run_id="sample-reject",
                    files_changed=(".git/config",),
                    patch="--- a/.git/config\n+++ b/.git/config\n@@\n+# bad\n",
                    rationale="forbidden path",
                    expected_effect="should reject",
                    verification_plan=("target_verification",),
                )
            ]
        ),
    ).run(_event("sample-reject"))
    if r2.policy_outcome is not PolicyOutcome.REJECT:
        raise SystemExit(f"expected REJECT, got {r2.policy_outcome} / {r2.status}")
    entries.append(
        (
            "02-reject",
            r2,
            art2,
            "Technical PASS + forbidden .git/ path → policy REJECT (phase-8 analogue)",
        )
    )

    # --- 03 ESCALATE (auth change) ---
    art3 = _reset_label("03-escalate")
    ws3 = art3 / "workspace"
    (ws3 / "auth").mkdir(parents=True)
    (ws3 / "src").mkdir(parents=True)
    (ws3 / "auth" / "permissions.py").write_text("ALLOW=False\n", encoding="utf-8")
    (ws3 / "src" / "app.py").write_text("ok\n", encoding="utf-8")
    r3 = AgentExecutionFoundation(
        workspace_root=ws3,
        artifacts_root=art3,
        enable_persistence=True,
        target_pass_schedule=[True],
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p-esc",
                    run_id="sample-escalate",
                    files_changed=("auth/permissions.py",),
                    patch="--- a/auth/permissions.py\n+++ b/auth/permissions.py\n@@\n+# x\n",
                    rationale="auth change",
                    expected_effect="needs human",
                    verification_plan=("target_verification",),
                )
            ]
        ),
    ).run(_event("sample-escalate", changed_paths=("auth/permissions.py",)))
    if r3.policy_outcome is not PolicyOutcome.ESCALATE:
        raise SystemExit(f"expected ESCALATE, got {r3.policy_outcome} / {r3.status}")
    entries.append(
        (
            "03-escalate",
            r3,
            art3,
            "Auth change → policy ESCALATE / AWAITING_HUMAN (BENCH-ESC-001 analogue)",
        )
    )

    # --- 04 HUMAN APPROVE (M4 slice: AWAITING_HUMAN → human decide → APPROVED) ---
    art4 = _reset_label("04-human-approve")
    ws4 = art4 / "workspace"
    (ws4 / "auth").mkdir(parents=True)
    (ws4 / "src").mkdir(parents=True)
    (ws4 / "auth" / "permissions.py").write_text("ALLOW=False\n", encoding="utf-8")
    (ws4 / "src" / "app.py").write_text("ok\n", encoding="utf-8")
    primary_before = (ws4 / "auth" / "permissions.py").read_text(encoding="utf-8")
    r4 = AgentExecutionFoundation(
        workspace_root=ws4,
        artifacts_root=art4,
        enable_persistence=True,
        target_pass_schedule=[True],
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p-human",
                    run_id="sample-human-approve",
                    files_changed=("auth/permissions.py",),
                    patch="--- a/auth/permissions.py\n+++ b/auth/permissions.py\n@@\n+# x\n",
                    rationale="auth change needing human",
                    expected_effect="human approve without primary apply",
                    verification_plan=("target_verification",),
                )
            ]
        ),
    ).run(_event("sample-human-approve", changed_paths=("auth/permissions.py",)))
    if r4.policy_outcome is not PolicyOutcome.ESCALATE:
        raise SystemExit(f"expected ESCALATE before human decide, got {r4.policy_outcome}")
    decided = apply_reviewer_decision(
        art4,
        "sample-human-approve",
        action="APPROVE",
        reviewer_id="sample-reviewer",
        comment="Synthetic M4 human decision; primary tree must not change.",
    )
    if decided.workflow_status_after != "APPROVED":
        raise SystemExit(f"expected human APPROVED, got {decided}")
    if decided.primary_workspace_mutated:
        raise SystemExit("primary_workspace_mutated must be False")
    primary_after = (ws4 / "auth" / "permissions.py").read_text(encoding="utf-8")
    if primary_after != primary_before:
        raise SystemExit("human APPROVE mutated primary workspace — invariant broken")
    entries.append(
        (
            "04-human-approve",
            r4,
            art4,
            "Auth ESCALATE → foundation-decide APPROVE (no primary apply) — M4 human-loop slice",
            {
                "workflow_status": "APPROVED",
                "policy_outcome": "ESCALATE",
                "human_action": "APPROVE",
                "primary_workspace_mutated": False,
            },
        )
    )

    manifest_artifacts: list[dict] = []
    for item in entries:
        if len(item) == 5:
            label, result, art, purpose, overrides = item
        else:
            label, result, art, purpose = item
            overrides = {}
        run_id = result.run.run_id
        report = verify_run_consistency(artifacts_root=art, run_id=run_id)
        if not report.valid:
            raise SystemExit(f"consistency failed for {label}: {report}")
        info = inspect_run(art, run_id)
        ws = art / "workspace"
        if ws.exists():
            shutil.rmtree(ws)
        workflow_status = overrides.get("workflow_status", result.status.value)
        if info.workflow_status != workflow_status and "workflow_status" in overrides:
            # Prefer durable state after human decide
            workflow_status = info.workflow_status
        policy_outcome = overrides.get(
            "policy_outcome",
            None if result.policy_outcome is None else result.policy_outcome.value,
        )
        summary = {
            "label": label,
            "purpose": purpose,
            "run_id": run_id,
            "workflow_status": workflow_status,
            "technical_status": result.technical_status,
            "policy_outcome": policy_outcome,
            "consistency_valid": report.valid,
            "evidence_root": f"evidence/sample-runs/{label}/runs/{run_id}",
            "synthetic": True,
            "git_commit": commit,
            "note": (
                "Local deterministic simulation with scripted proposals. "
                "Policy/human APPROVE does not mutate a primary product workspace."
            ),
        }
        if "human_action" in overrides:
            summary["human_action"] = overrides["human_action"]
            summary["primary_workspace_mutated"] = overrides.get(
                "primary_workspace_mutated", False
            )
        (art / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        manifest_artifacts.append(
            {
                "artifact": f"evidence/sample-runs/{label}/",
                "summary": f"evidence/sample-runs/{label}/summary.json",
                "source": "ci_failure_orchestrator.foundation.AgentExecutionFoundation",
                "generated_by": "scripts/generate_sample_evidence.py",
                "git_commit": commit,
                "purpose": purpose,
                "run_id": run_id,
                "workflow_status": summary["workflow_status"],
                "policy_outcome": summary["policy_outcome"],
                "synthetic": True,
                "reproduce": "python scripts/generate_sample_evidence.py",
                "verify": (
                    f"ci-orchestrator foundation-verify {run_id} "
                    f"--artifacts evidence/sample-runs/{label}"
                ),
            }
        )
        print(f"{label}: {run_id} {summary['policy_outcome']} {summary['workflow_status']}")

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "maturity": "M3+M4-slice",
        "evidence_level": "E4-simulated",
        "disclaimer": (
            "Sample runs are deterministic local simulations with scripted proposals. "
            "They are not production workload evidence (not E5). "
            "04-human-approve demonstrates the human decision loop only."
        ),
        "artifacts": manifest_artifacts,
    }
    (EVIDENCE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {EVIDENCE / 'manifest.json'} @ {commit[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""M4 slice — human decision resume from AWAITING_HUMAN."""

from __future__ import annotations

from pathlib import Path

from ci_failure_orchestrator.foundation import (
    AgentExecutionFoundation,
    ScriptedProposalFactory,
    apply_reviewer_decision,
    resume_run,
    verify_run_consistency,
)
from ci_failure_orchestrator.foundation.models import FailureEvent, RepairProposal, RunStatus, new_id
from ci_failure_orchestrator.foundation.persistence import (
    FileStateStore,
    HumanDecisionStatus,
    RecoveryStatus,
    replay_events,
)
from ci_failure_orchestrator.foundation.policy import PolicyOutcome


def _event(run_id: str, *, changed_paths: tuple[str, ...] = ("auth/permissions.py",)) -> FailureEvent:
    return FailureEvent(
        event_id=new_id("evt"),
        run_id=run_id,
        source="test",
        workflow="ci",
        job="test",
        failed_step="pytest",
        message="AssertionError",
        changed_paths=changed_paths,
        exit_code=1,
    )


def _escalate_to_awaiting(tmp_path: Path, run_id: str) -> Path:
    ws = tmp_path / "workspace"
    (ws / "auth").mkdir(parents=True)
    (ws / "auth" / "permissions.py").write_text("ALLOW=False\n", encoding="utf-8")
    result = AgentExecutionFoundation(
        workspace_root=ws,
        artifacts_root=tmp_path,
        enable_persistence=True,
        target_pass_schedule=[True],
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p-esc",
                    run_id=run_id,
                    files_changed=("auth/permissions.py",),
                    patch="--- a/auth/permissions.py\n+++ b/auth/permissions.py\n@@\n+# x\n",
                    rationale="auth change",
                    expected_effect="needs human",
                    verification_plan=("target_verification",),
                )
            ]
        ),
    ).run(_event(run_id))
    assert result.status is RunStatus.AWAITING_HUMAN
    assert result.policy_outcome is PolicyOutcome.ESCALATE
    return tmp_path


def test_human_approve_leaves_awaiting_without_primary_apply(tmp_path: Path) -> None:
    arts = _escalate_to_awaiting(tmp_path, "m4-approve")
    primary = arts / "workspace" / "auth" / "permissions.py"
    before = primary.read_text(encoding="utf-8")

    decision = resume_run(arts, "m4-approve")
    assert decision.status is RecoveryStatus.TERMINAL
    assert "foundation-decide" in decision.message

    result = apply_reviewer_decision(
        arts,
        "m4-approve",
        action="APPROVE",
        reviewer_id="alice",
        comment="looks intentional",
    )
    assert result.status is HumanDecisionStatus.APPLIED
    assert result.workflow_status_before == "AWAITING_HUMAN"
    assert result.workflow_status_after == "APPROVED"
    assert result.primary_workspace_mutated is False
    assert primary.read_text(encoding="utf-8") == before

    state = FileStateStore(arts).load_run("m4-approve")
    assert state.workflow_status == "APPROVED"
    assert state.reviewer_decision_ref
    assert (arts / "runs" / "m4-approve" / state.reviewer_decision_ref).is_file()
    timeline = replay_events(arts, "m4-approve")
    assert any("HUMAN_DECISION_RECORDED" in t for t in timeline)
    assert any("HUMAN_APPROVED" in t for t in timeline)
    report = verify_run_consistency(artifacts_root=arts, run_id="m4-approve")
    assert report.valid, report.issues


def test_human_reject(tmp_path: Path) -> None:
    arts = _escalate_to_awaiting(tmp_path, "m4-reject")
    result = apply_reviewer_decision(arts, "m4-reject", action="REJECT", reviewer_id="bob")
    assert result.status is HumanDecisionStatus.APPLIED
    assert result.workflow_status_after == "REJECTED"
    timeline = replay_events(arts, "m4-reject")
    assert any("HUMAN_REJECTED" in t for t in timeline)


def test_human_defer_stays_awaiting(tmp_path: Path) -> None:
    arts = _escalate_to_awaiting(tmp_path, "m4-defer")
    result = apply_reviewer_decision(arts, "m4-defer", action="DEFER", reviewer_id="carol")
    assert result.status is HumanDecisionStatus.RECORDED
    assert result.workflow_status_after == "AWAITING_HUMAN"
    state = FileStateStore(arts).load_run("m4-defer")
    assert state.workflow_status == "AWAITING_HUMAN"
    assert state.reviewer_decision_ref


def test_decide_blocked_when_not_awaiting(tmp_path: Path) -> None:
    result = AgentExecutionFoundation(artifacts_root=tmp_path, enable_persistence=True).run(
        _event("m4-ok", changed_paths=("src/app.py",))
    )
    assert result.status is RunStatus.APPROVED
    blocked = apply_reviewer_decision(tmp_path, "m4-ok", action="APPROVE")
    assert blocked.status is HumanDecisionStatus.BLOCKED

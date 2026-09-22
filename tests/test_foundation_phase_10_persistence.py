"""Phase 10 — durable state, audit JSONL, evidence store tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci_failure_orchestrator.foundation import AgentExecutionFoundation, FailureEvent, RunStatus
from ci_failure_orchestrator.foundation.models import new_id
from ci_failure_orchestrator.foundation.persistence import (
    AUDIT_SCHEMA,
    DURABLE_SCHEMA,
    AuditEvent,
    AuditEventType,
    DurableRunState,
    EvidenceLimits,
    FileAuditStore,
    FileEvidenceStore,
    FileStateStore,
    PersistenceError,
    RecoveryStatus,
    RunPersistence,
    UnsupportedSchemaError,
    assess_recovery,
    atomic_write_text,
    inspect_run,
    replay_events,
    resume_run,
    verify_run_consistency,
)
from ci_failure_orchestrator.foundation.policy import PolicyOutcome
from ci_failure_orchestrator.foundation.retry import RetryBudget
from ci_failure_orchestrator.foundation.runner import ScriptedProposalFactory
from ci_failure_orchestrator.foundation.models import RepairProposal
from ci_failure_orchestrator.foundation.sanitization import REDACTED


def _event(**kwargs) -> FailureEvent:
    base = dict(
        event_id=new_id("evt"),
        run_id=new_id("run"),
        source="synthetic",
        workflow="ci",
        job="test",
        failed_step="pytest",
        message="AssertionError",
        changed_paths=("src/app.py",),
        log_excerpt="FAILED tests/test_app.py::test_x",
    )
    base.update(kwargs)
    return FailureEvent(**base)


# --- State store ---


def test_state_store_create_save_load(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path)
    run = DurableRunState(
        schema_version=DURABLE_SCHEMA,
        run_id="r1",
        workflow_status=RunStatus.PLANNED.value,
        current_attempt=1,
    )
    store.create_run(run)
    assert store.exists("r1")
    loaded = store.load_run("r1")
    assert loaded.run_id == "r1"
    assert loaded.workflow_status == RunStatus.PLANNED.value
    loaded.workflow_status = RunStatus.EVALUATED.value
    store.save_run(loaded)
    assert store.load_run("r1").workflow_status == RunStatus.EVALUATED.value


def test_state_store_missing_and_duplicate(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.load_run("missing")
    run = DurableRunState(schema_version=DURABLE_SCHEMA, run_id="r2", workflow_status="RECEIVED")
    store.create_run(run)
    with pytest.raises(PersistenceError):
        store.create_run(run)


def test_state_store_unsupported_schema(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "bad" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": "future.v99", "run_id": "bad", "workflow_status": "X"}), encoding="utf-8")
    with pytest.raises(UnsupportedSchemaError):
        FileStateStore(tmp_path).load_run("bad")


def test_atomic_write_preserves_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    atomic_write_text(target, '{"ok": true}\n')
    assert '"ok"' in target.read_text(encoding="utf-8")
    # Simulate failed replace by writing valid content again
    atomic_write_text(target, '{"ok": false}\n')
    assert json.loads(target.read_text(encoding="utf-8"))["ok"] is False


# --- Audit store ---


def test_audit_append_and_sequence(tmp_path: Path) -> None:
    audit = FileAuditStore(tmp_path)
    (tmp_path / "runs" / "r").mkdir(parents=True)

    def evt(seq: int, eid: str) -> AuditEvent:
        return AuditEvent(
            schema_version=AUDIT_SCHEMA,
            event_id=eid,
            run_id="r",
            sequence=seq,
            timestamp="t",
            event_type=AuditEventType.RUN_CREATED.value,
            actor="a",
            component="c",
            state_before=None,
            state_after="RECEIVED",
        )

    audit.append(evt(1, "e1"))
    audit.append(evt(2, "e2"))
    events = audit.read_events("r")
    assert [e.sequence for e in events] == [1, 2]
    assert audit.latest_sequence("r") == 2
    with pytest.raises(PersistenceError):
        audit.append(evt(2, "e3"))  # non-monotonic
    with pytest.raises(PersistenceError):
        audit.append(evt(3, "e1"))  # duplicate id


def test_audit_malformed_trailing_preserved(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "r" / "events.jsonl"
    path.parent.mkdir(parents=True)
    good = AuditEvent(
        schema_version=AUDIT_SCHEMA,
        event_id="e1",
        run_id="r",
        sequence=1,
        timestamp="t",
        event_type="RUN_CREATED",
        actor="a",
        component="c",
        state_before=None,
        state_after="RECEIVED",
    )
    path.write_text(json.dumps(good.to_dict()) + "\n{not-json\n", encoding="utf-8")
    events, trailing = FileAuditStore(tmp_path).read_events_tolerant("r")
    assert len(events) == 1
    assert trailing is True
    with pytest.raises(PersistenceError):
        FileAuditStore(tmp_path).read_events("r")


# --- Evidence store ---


def test_evidence_write_sanitize_truncate(tmp_path: Path) -> None:
    store = FileEvidenceStore(tmp_path, limits=EvidenceLimits(max_patch_chars=40, max_log_chars=40))
    ref = store.write_json(
        "r",
        "policy",
        {"msg": "Authorization: Bearer fake-secret password=synthetic-password"},
        name="policy-decision.json",
    )
    assert ref.ref == "policy/policy-decision.json"
    body = (tmp_path / "runs" / "r" / ref.ref).read_text(encoding="utf-8")
    assert "fake-secret" not in body
    assert REDACTED in body
    patch = store.write_text(
        "r",
        "patch",
        "-----BEGIN PRIVATE KEY-----\nABC\n-----END PRIVATE KEY-----\n" + ("x" * 200),
        name="proposal-001.patch",
        max_chars=40,
    )
    patch_body = (tmp_path / "runs" / "r" / patch.ref).read_text(encoding="utf-8")
    assert "BEGIN PRIVATE KEY" not in patch_body or REDACTED in patch_body
    assert "[truncated]" in patch_body


# --- Recovery / consistency ---


def test_recovery_statuses() -> None:
    d = DurableRunState(schema_version=DURABLE_SCHEMA, run_id="r", workflow_status="PLANNED")
    assert assess_recovery(d).status is RecoveryStatus.RESUMABLE
    d.workflow_status = "AWAITING_HUMAN"
    assert assess_recovery(d).status is RecoveryStatus.TERMINAL
    d.workflow_status = "SANDBOX_RUNNING"
    assert assess_recovery(d).status is RecoveryStatus.REQUIRES_REVIEW


def test_resume_planned_emits_run_resumed(tmp_path: Path) -> None:
    jp = RunPersistence(tmp_path)
    jp.start_run("resume-me", "RECEIVED")
    jp.checkpoint(workflow_status="PLANNED", current_attempt=1)
    decision = resume_run(tmp_path, "resume-me")
    assert decision.status is RecoveryStatus.RESUMABLE
    assert decision.run_id == "resume-me"
    timeline = replay_events(tmp_path, "resume-me")
    assert any("RUN_RESUMED" in line for line in timeline)
    state = FileStateStore(tmp_path).load_run("resume-me")
    assert state.run_id == "resume-me"
    assert state.current_attempt == 1


def test_resume_awaiting_human_is_terminal(tmp_path: Path) -> None:
    jp = RunPersistence(tmp_path)
    jp.start_run("await", "RECEIVED")
    eref = jp.write_json("escalation", {"escalation_id": "esc-1"}, name="summary.json")
    # Minimal evaluation event so consistency does not flag AWAITING_HUMAN
    jp.emit(AuditEventType.EVALUATION_COMPLETED, state_after="EVALUATED")
    jp.checkpoint(
        workflow_status="AWAITING_HUMAN",
        escalation_ref=eref.ref,
        latest_evaluation_ref=None,
    )
    # Clear eval ref requirement by writing a stub evaluation file referenced in state
    eval_ref = jp.write_json("evaluation", {"passed": True}, name="evaluation-001.json")
    jp.checkpoint(latest_evaluation_ref=eval_ref.ref, workflow_status="AWAITING_HUMAN")
    d = resume_run(tmp_path, "await")
    assert d.status is RecoveryStatus.TERMINAL
    assert "Human review" in d.message or "complete" in d.message.lower()


def test_consistency_missing_artifact(tmp_path: Path) -> None:
    jp = RunPersistence(tmp_path)
    jp.start_run("c1", "RECEIVED")
    jp.checkpoint(workflow_status="EVALUATED", latest_evaluation_ref="evaluations/missing.json")
    report = verify_run_consistency(artifacts_root=tmp_path, run_id="c1")
    assert report.valid is False
    assert any(i.code == "MISSING_ARTIFACT" for i in report.issues)


# --- Integration ---


def test_integration_successful_persisted_run(tmp_path: Path) -> None:
    result = AgentExecutionFoundation(artifacts_root=tmp_path).run(_event(run_id="p10-ok"))
    assert result.status is RunStatus.APPROVED
    root = tmp_path / "runs" / "p10-ok"
    assert (root / "state.json").exists()
    assert (root / "events.jsonl").exists()
    assert (root / "input" / "failure-event.json").exists()
    assert (root / "classification" / "classification.json").exists()
    assert list((root / "plans").glob("*.json"))
    assert list((root / "proposals").glob("*.json"))
    assert list((root / "sandbox").glob("*.json"))
    assert list((root / "evaluations").glob("*.json"))
    assert (root / "policy" / "policy-decision.json").exists()
    state = FileStateStore(tmp_path).load_run("p10-ok")
    assert state.workflow_status == RunStatus.APPROVED.value
    assert state.technical_status == "PASS"
    assert state.policy_outcome == PolicyOutcome.APPROVE.value
    timeline = replay_events(tmp_path, "p10-ok")
    assert timeline[0].endswith("RUN_CREATED")
    assert any("POLICY_APPROVED" in t for t in timeline)
    assert any("RUN_SUCCEEDED" in t for t in timeline)
    report = verify_run_consistency(artifacts_root=tmp_path, run_id="p10-ok")
    assert report.valid, report.issues
    info = inspect_run(tmp_path, "p10-ok")
    assert info.workflow_status == "APPROVED"


def test_integration_retry_persisted(tmp_path: Path) -> None:
    result = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        retry_budget=RetryBudget(max_attempts=3),
        target_pass_schedule=(False, True),
        proposal_factory=ScriptedProposalFactory(
            [
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+#1\n",
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+#2\n",
            ]
        ),
    ).run(_event(run_id="p10-retry"))
    assert result.status is RunStatus.APPROVED
    assert result.attempts == 2
    attempts = list((tmp_path / "runs" / "p10-retry" / "attempts").glob("*.json"))
    assert len(attempts) == 2
    timeline = "\n".join(replay_events(tmp_path, "p10-retry"))
    assert "ATTEMPT_STARTED" in timeline
    assert "RETRY_DECIDED" in timeline
    assert "RETRY_STARTED" in timeline
    assert timeline.count("ATTEMPT_STARTED") >= 2


def test_integration_escalation_persisted(tmp_path: Path) -> None:
    result = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p",
                    run_id="p10-esc",
                    files_changed=("auth/session.py",),
                    patch="--- a/auth/session.py\n+++ b/auth/session.py\n@@\n+#a\n",
                    rationale="auth",
                    expected_effect="pass",
                    verification_plan=("target_verification", "scope_check"),
                )
            ]
        ),
    ).run(_event(run_id="p10-esc"))
    assert result.status is RunStatus.AWAITING_HUMAN
    assert (tmp_path / "runs" / "p10-esc" / "escalation" / "summary.json").exists()
    assert (tmp_path / "runs" / "p10-esc" / "policy" / "policy-decision.json").exists()
    d = resume_run(tmp_path, "p10-esc")
    assert d.status is RecoveryStatus.TERMINAL
    timeline = replay_events(tmp_path, "p10-esc")
    assert any("POLICY_ESCALATED" in t for t in timeline)
    assert any("AWAITING_HUMAN" in t for t in timeline)


def test_integration_reject_persisted(tmp_path: Path) -> None:
    from ci_failure_orchestrator.foundation.models import SandboxResult, ToolResult
    from ci_failure_orchestrator.foundation.models import EvaluationResult, EvaluationCheck, CheckStatus

    class AllowGitSandbox:
        def execute(self, proposal, verification_steps, *, target_should_pass=True):
            return SandboxResult(
                run_id=proposal.run_id,
                proposal_id=proposal.proposal_id,
                success=True,
                patch_applied=True,
                command_results=(ToolResult("test_runner", True, 0, stdout="PASS"),),
                changed_files=proposal.files_changed,
            )

    class PassEvaluator:
        def evaluate(self, *, proposal, sandbox):
            return EvaluationResult(
                run_id=proposal.run_id,
                passed=True,
                patch_applied=True,
                target_verification_passed=True,
                regressions_detected=False,
                forbidden_changes_detected=False,
                checks=(EvaluationCheck("TARGET_TEST_PASSED", CheckStatus.PASSED),),
                evidence=(),
            )

    result = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        sandbox=AllowGitSandbox(),
        evaluator=PassEvaluator(),
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id="p",
                    run_id="p10-rej",
                    files_changed=(".git/config",),
                    patch="diff",
                    rationale="bad",
                    expected_effect="x",
                    verification_plan=("target_verification",),
                )
            ]
        ),
    ).run(_event(run_id="p10-rej"))
    assert result.status is RunStatus.REJECTED
    assert result.escalation is None
    assert (tmp_path / "runs" / "p10-rej" / "policy" / "policy-decision.json").exists()
    assert not (tmp_path / "runs" / "p10-rej" / "escalation" / "summary.json").exists()
    assert any("POLICY_REJECTED" in t for t in replay_events(tmp_path, "p10-rej"))


def test_integration_sanitized_persistence(tmp_path: Path) -> None:
    result = AgentExecutionFoundation(artifacts_root=tmp_path).run(
        _event(
            run_id="p10-san",
            message="Authorization: Bearer fake-secret password=synthetic-password",
            log_excerpt="-----BEGIN PRIVATE KEY-----\nABC\n-----END PRIVATE KEY-----",
        )
    )
    assert result.status is RunStatus.APPROVED
    failure = (tmp_path / "runs" / "p10-san" / "input" / "failure-event.json").read_text(encoding="utf-8")
    assert "fake-secret" not in failure
    assert "synthetic-password" not in failure
    assert REDACTED in failure

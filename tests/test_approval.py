from ci_failure_orchestrator.approval import ApprovalContext, ApprovalDecision, HumanApprovalGate


def test_human_approval_required_for_high_risk_paths():
    gate = HumanApprovalGate()
    context = ApprovalContext(
        policy_decision="release",
        evaluation_score=0.99,
        regression_free=True,
        changed_files=("infra/deploy.yaml",),
    )
    result = gate.evaluate(context, human_approved=None)
    assert result.decision is ApprovalDecision.REQUIRED


def test_human_approval_accepts_when_approved():
    gate = HumanApprovalGate()
    context = ApprovalContext(
        policy_decision="release",
        evaluation_score=0.99,
        regression_free=True,
        changed_files=("src/a.py",),
    )
    result = gate.evaluate(context, human_approved=True)
    assert result.decision is ApprovalDecision.APPROVED

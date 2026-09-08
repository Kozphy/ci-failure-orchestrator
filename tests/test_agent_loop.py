from ci_failure_orchestrator.agent_executor import CodingAgentExecutor, PatchProposal
from ci_failure_orchestrator.agent_loop import AgentRepairLoop, EvaluationResult
from ci_failure_orchestrator.evaluator import RetryBudget
from ci_failure_orchestrator.repair_planner import RepairPlan


class FakeAgent:
    name = "fake"

    def __init__(self, changed_files=("src/app.py",), patch="diff --git a/src/app.py b/src/app.py"):
        self.changed_files = changed_files
        self.patch = patch
        self.calls = 0

    def propose_patch(self, plan):
        self.calls += 1
        return PatchProposal(
            provider=self.name,
            summary="minimal repair",
            changed_files=self.changed_files,
            patch=self.patch,
            confidence=0.9,
        )


def make_plan(*, approval=False):
    return RepairPlan(
        root_stage="typecheck",
        hypothesis="type failure is causal",
        target_files=("src/app.py",),
        proposed_change="fix type contract",
        verification=(),
        risk="high" if approval else "low",
        requires_human_approval=approval,
    )


def test_executor_rejects_out_of_scope_patch():
    result = CodingAgentExecutor().execute(
        FakeAgent(changed_files=("src/other.py",)), make_plan()
    )
    assert not result.accepted
    assert "outside" in result.reason


def test_high_risk_plan_requires_approval_before_agent_runs():
    agent = FakeAgent()
    result = CodingAgentExecutor().execute(agent, make_plan(approval=True))
    assert not result.accepted
    assert agent.calls == 0


def test_loop_reaches_policy_gate_after_independent_evaluation():
    agent = FakeAgent()
    loop = AgentRepairLoop()
    result = loop.run(
        agent,
        make_plan(),
        lambda _: EvaluationResult(True, True, 0.95, "all checks passed"),
        budget=RetryBudget(max_attempts=2),
    )
    assert result.action == "READY_FOR_POLICY_GATE"
    assert result.attempts == 1


def test_loop_stops_on_regression():
    result = AgentRepairLoop().run(
        FakeAgent(),
        make_plan(),
        lambda _: EvaluationResult(True, False, 0.4, "regression"),
    )
    assert result.action == "ROLLBACK_AND_ESCALATE"


def test_loop_stops_when_retry_budget_is_exhausted():
    result = AgentRepairLoop().run(
        FakeAgent(),
        make_plan(),
        lambda _: EvaluationResult(False, True, 0.3, "target still failing"),
        budget=RetryBudget(max_attempts=2),
    )
    assert result.action == "ESCALATE_HUMAN"
    assert result.attempts == 2
    assert result.reason == "retry budget exhausted"

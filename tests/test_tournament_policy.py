from ci_failure_orchestrator.agent_executor import PatchProposal
from ci_failure_orchestrator.agent_loop import EvaluationResult
from ci_failure_orchestrator.models import Failure, RankedFailure, Stage
from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.policy import RepairPolicyGate
from ci_failure_orchestrator.production_evidence import build_production_evidence
from ci_failure_orchestrator.repair_planner import DeterministicRepairPlanner
from ci_failure_orchestrator.tournament import RepairTournament


class FakeAgent:
    def __init__(self, name: str, confidence: float, patch: str = "diff --git"):
        self.name = name
        self.confidence = confidence
        self.patch = patch

    def propose_patch(self, plan):
        return PatchProposal(
            provider=self.name,
            summary=f"proposal from {self.name}",
            changed_files=("src/a.py",),
            patch=self.patch,
            confidence=self.confidence,
        )


def _plan():
    graph = PipelineGraph([Stage("typecheck")])
    failure = Failure(
        "typecheck",
        "TYPE_ERROR",
        confidence=0.95,
        metadata={"files": ["src/a.py"]},
    )
    ranked = RankedFailure(failure, 0.95, 0, 0, 1, ["upstream root"])
    return DeterministicRepairPlanner().plan(graph, ranked, {"typecheck"})


def test_tournament_selects_highest_utility_candidate():
    plan = _plan()
    agents = [FakeAgent("cheap", 0.9), FakeAgent("expensive", 0.9)]

    def evaluate(execution):
        return EvaluationResult(True, True, 0.92, "passed")

    def telemetry(execution):
        if execution.proposal.provider == "cheap":
            return (0.02, 500)
        return (0.40, 20_000)

    result = RepairTournament().run(agents, plan, evaluate, telemetry=telemetry)
    assert result.action == "READY_FOR_POLICY_GATE"
    assert result.winner is not None
    assert result.winner.agent_name == "cheap"


def test_tournament_rejects_regression_candidate():
    plan = _plan()

    def evaluate(execution):
        return EvaluationResult(True, False, 0.99, "regression")

    result = RepairTournament().run([FakeAgent("bad", 0.99)], plan, evaluate)
    assert result.action == "ESCALATE_HUMAN"
    assert result.winner is None


def test_policy_gate_blocks_budget_overrun():
    plan = _plan()

    def evaluate(execution):
        return EvaluationResult(True, True, 0.95, "passed")

    result = RepairTournament().run(
        [FakeAgent("costly", 0.9)],
        plan,
        evaluate,
        telemetry=lambda execution: (0.75, 1_000),
    )
    decision = RepairPolicyGate(max_cost_usd=0.50).decide(result)
    assert decision.action == "HUMAN_APPROVAL_REQUIRED"
    assert decision.requires_human_approval


def test_production_evidence_is_stable_and_complete():
    plan = _plan()

    def evaluate(execution):
        return EvaluationResult(True, True, 0.95, "passed")

    result = RepairTournament().run([FakeAgent("winner", 0.9)], plan, evaluate)
    decision = RepairPolicyGate().decide(result)
    evidence = build_production_evidence(
        root_stage=plan.root_stage,
        tournament=result,
        policy=decision,
    )
    assert evidence.selected_agent == "winner"
    assert evidence.candidate_count == 1
    assert len(evidence.evidence_hash) == 64

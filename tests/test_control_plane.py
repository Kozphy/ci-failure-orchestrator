from ci_failure_orchestrator.control_plane import Decision, RepairControlPlane
from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.models import Failure, Stage
from ci_failure_orchestrator.policy import DefaultRepairPolicy
from ci_failure_orchestrator.production import InMemoryEvidenceSink, RegressionAwareEvaluator
from ci_failure_orchestrator.repair_agents import DeterministicRepairAgent, GeneralCodingAgent, TestRepairAgent


def graph() -> PipelineGraph:
    return PipelineGraph([
        Stage("lint"),
        Stage("typecheck", depends_on=("lint",)),
        Stage("unit", depends_on=("typecheck",)),
        Stage("integration", depends_on=("unit",)),
        Stage("build", depends_on=("integration",)),
    ])


def test_release_after_verified_repair() -> None:
    evidence = InMemoryEvidenceSink()
    control = RepairControlPlane(
        graph(),
        [DeterministicRepairAgent(), GeneralCodingAgent()],
        RegressionAwareEvaluator(tests_passed=True, regression_free=True, score=0.97),
        DefaultRepairPolicy(),
        evidence,
    )
    failure = Failure("typecheck", "", "mypy incompatible type in assignment")
    assert control.run(failure) is Decision.RELEASE
    assert failure.error_type == "TYPE_ERROR"
    assert [e["event"] for e in evidence.events] == ["classified", "evaluated", "policy_decision"]


def test_regression_blocks_release() -> None:
    evidence = InMemoryEvidenceSink()
    control = RepairControlPlane(
        graph(),
        [TestRepairAgent(), GeneralCodingAgent()],
        RegressionAwareEvaluator(tests_passed=True, regression_free=False, score=0.99),
        DefaultRepairPolicy(),
        evidence,
    )
    failure = Failure("unit", "", "AssertionError expected 2 got 3")
    assert control.run(failure) is Decision.BLOCK


def test_unknown_failure_escalates() -> None:
    evidence = InMemoryEvidenceSink()
    control = RepairControlPlane(
        graph(),
        [DeterministicRepairAgent(), GeneralCodingAgent()],
        RegressionAwareEvaluator(),
        DefaultRepairPolicy(),
        evidence,
    )
    failure = Failure("build", "", "something unprecedented happened")
    assert control.run(failure) is Decision.ESCALATE
    assert evidence.events[-1]["payload"]["reason"] == "no_repair_plan"


def test_cost_budget_stops_autonomy() -> None:
    evidence = InMemoryEvidenceSink()
    control = RepairControlPlane(
        graph(),
        [DeterministicRepairAgent()],
        RegressionAwareEvaluator(),
        DefaultRepairPolicy(),
        evidence,
        max_cost=0.001,
    )
    failure = Failure("typecheck", "", "mypy incompatible type")
    assert control.run(failure) is Decision.ESCALATE
    assert evidence.events[-1]["payload"]["reason"] == "budget_or_stopping_condition"

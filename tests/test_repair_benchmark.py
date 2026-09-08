from ci_failure_orchestrator.control_plane import Decision, RepairControlPlane
from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.models import Failure, Stage
from ci_failure_orchestrator.policy import DefaultRepairPolicy
from ci_failure_orchestrator.production import InMemoryEvidenceSink, RegressionAwareEvaluator
from ci_failure_orchestrator.repair_agents import DeterministicRepairAgent, GeneralCodingAgent
from ci_failure_orchestrator.repair_benchmark import RepairBenchmarkCase, evaluate_repairs


def control() -> RepairControlPlane:
    graph = PipelineGraph([
        Stage("lint"),
        Stage("typecheck", depends_on=("lint",)),
        Stage("unit", depends_on=("typecheck",)),
        Stage("build", depends_on=("unit",)),
    ])
    return RepairControlPlane(
        graph,
        [DeterministicRepairAgent(), GeneralCodingAgent()],
        RegressionAwareEvaluator(tests_passed=True, regression_free=True, score=0.97),
        DefaultRepairPolicy(),
        InMemoryEvidenceSink(),
    )


def test_repair_benchmark_reports_success_cost_latency() -> None:
    cases = [
        RepairBenchmarkCase(
            "type-error",
            Failure("typecheck", "", "mypy incompatible type in assignment"),
            Decision.RELEASE,
        ),
        RepairBenchmarkCase(
            "unknown",
            Failure("build", "", "something unprecedented happened"),
            Decision.ESCALATE,
        ),
    ]
    results, summary = evaluate_repairs(cases, control)
    assert summary.cases == 2
    assert summary.passed == 2
    assert summary.success_rate == 1.0
    assert summary.mean_cost >= 0.0
    assert summary.median_latency_ms >= 0.0
    assert results[0].decision == "release"
    assert results[1].decision == "escalate"

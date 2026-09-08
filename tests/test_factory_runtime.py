from __future__ import annotations

from ci_failure_orchestrator.factory_governance import RiskGovernanceGate
from ci_failure_orchestrator.factory_runtime import (
    GoalDrivenFactory,
    GoalRequest,
    InMemoryEvidenceStore,
)
from ci_failure_orchestrator.software_factory import EvaluationResult, TaskStatus
from ci_failure_orchestrator.spec_engine import FactorySpec, TaskSpec


class StaticSpecProvider:
    def generate(self, request: GoalRequest) -> FactorySpec:
        assert request.goal
        return FactorySpec(
            goal=request.goal,
            tasks=(
                TaskSpec(
                    id="build",
                    title="Build feature",
                    goal="Implement the feature",
                    acceptance=("tests pass",),
                ),
                TaskSpec(
                    id="verify",
                    title="Verify feature",
                    goal="Run independent verification",
                    acceptance=("verification passes",),
                    dependencies=("build",),
                ),
            ),
        )


class RecordingRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, task) -> None:
        self.calls.append(task.id)


class PassingEvaluator:
    def evaluate(self, task) -> EvaluationResult:
        return EvaluationResult(passed=True, evidence=(f"{task.id}:ok",))


def test_goal_driven_factory_compiles_executes_and_records_evidence() -> None:
    runtime = RecordingRuntime()
    store = InMemoryEvidenceStore()
    factory = GoalDrivenFactory(
        spec_provider=StaticSpecProvider(),
        runtime=runtime,
        evaluator=PassingEvaluator(),
        governance=RiskGovernanceGate(),
        evidence_store=store,
    )

    result = factory.run(GoalRequest(goal="Ship a safe feature"))

    assert runtime.calls == ["build", "verify"]
    assert [task.status for task in result.tasks] == [TaskStatus.PASSED, TaskStatus.PASSED]
    assert [record.task_id for record in result.evidence] == ["build", "verify"]
    assert all(record.passed for record in result.evidence)


class RetryEvaluator:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, task) -> EvaluationResult:
        self.calls += 1
        if self.calls == 1:
            return EvaluationResult(passed=False, failures=("first attempt failed",))
        return EvaluationResult(passed=True, evidence=("repair verified",))


def test_evidence_store_keeps_failed_and_successful_attempts() -> None:
    store = InMemoryEvidenceStore()
    factory = GoalDrivenFactory(
        spec_provider=StaticSpecProvider(),
        runtime=RecordingRuntime(),
        evaluator=RetryEvaluator(),
        governance=RiskGovernanceGate(),
        evidence_store=store,
        max_attempts=3,
    )

    result = factory.run(GoalRequest(goal="Repair until verified"))

    build_records = [r for r in result.evidence if r.task_id == "build"]
    assert [r.passed for r in build_records] == [False, True]
    assert [r.attempt for r in build_records] == [1, 2]

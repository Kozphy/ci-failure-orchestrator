from ci_failure_orchestrator.factory_governance import RiskBasedGovernance
from ci_failure_orchestrator.software_factory import (
    AcceptanceCriterion,
    AutonomousSoftwareFactory,
    EvaluationResult,
    FactoryTask,
    TaskStatus,
)


class RecordingRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, task: FactoryTask) -> None:
        self.calls.append(task.id)


class PassEvaluator:
    def evaluate(self, task: FactoryTask) -> EvaluationResult:
        return EvaluationResult(passed=True, evidence=(f"{task.id}:pass",))


class FailThenPassEvaluator:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, task: FactoryTask) -> EvaluationResult:
        self.calls += 1
        return EvaluationResult(passed=self.calls >= 2)


def test_factory_runs_dependency_order() -> None:
    runtime = RecordingRuntime()
    factory = AutonomousSoftwareFactory(
        runtime=runtime,
        evaluator=PassEvaluator(),
        governance=RiskBasedGovernance(),
    )
    spec = FactoryTask(
        id="spec",
        title="Create executable spec",
        goal="Define acceptance criteria",
        acceptance=[AcceptanceCriterion("criteria are explicit")],
    )
    implementation = FactoryTask(
        id="impl",
        title="Implement feature",
        goal="Satisfy the executable spec",
        dependencies=["spec"],
    )

    result = factory.run([spec, implementation])

    assert [task.status for task in result] == [TaskStatus.PASSED, TaskStatus.PASSED]
    assert runtime.calls == ["spec", "impl"]


def test_factory_retries_until_evaluator_passes() -> None:
    task = FactoryTask(id="repair", title="Repair CI", goal="Make verification pass")
    runtime = RecordingRuntime()
    factory = AutonomousSoftwareFactory(
        runtime=runtime,
        evaluator=FailThenPassEvaluator(),
        governance=RiskBasedGovernance(),
        max_attempts=3,
    )

    factory.run([task])

    assert task.status is TaskStatus.PASSED
    assert task.attempts == 2
    assert runtime.calls == ["repair", "repair"]


def test_high_risk_task_is_blocked() -> None:
    task = FactoryTask(
        id="prod-db",
        title="Production database migration",
        goal="Change production schema",
        risk="high",
    )
    runtime = RecordingRuntime()
    factory = AutonomousSoftwareFactory(
        runtime=runtime,
        evaluator=PassEvaluator(),
        governance=RiskBasedGovernance(),
    )

    factory.run([task])

    assert task.status is TaskStatus.BLOCKED
    assert runtime.calls == []


def test_missing_dependency_is_rejected() -> None:
    task = FactoryTask(
        id="impl",
        title="Implement",
        goal="Build",
        dependencies=["missing"],
    )
    factory = AutonomousSoftwareFactory(
        runtime=RecordingRuntime(),
        evaluator=PassEvaluator(),
        governance=RiskBasedGovernance(),
    )

    try:
        factory.run([task])
    except ValueError as exc:
        assert "unknown dependency" in str(exc)
    else:
        raise AssertionError("expected ValueError")

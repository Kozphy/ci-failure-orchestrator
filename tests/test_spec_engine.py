import pytest

from ci_failure_orchestrator.spec_engine import (
    FactorySpec,
    SpecCompiler,
    SpecValidationError,
    TaskSpec,
)


def test_compile_turns_spec_into_factory_tasks():
    spec = FactorySpec(
        goal="Build and verify a health API",
        tasks=(
            TaskSpec(
                id="spec",
                title="Define behavior",
                goal="Define /health behavior",
                acceptance=("BDD scenario exists",),
            ),
            TaskSpec(
                id="impl",
                title="Implement endpoint",
                goal="Implement /health",
                acceptance=("GET /health returns 200",),
                dependencies=("spec",),
                risk="medium",
            ),
        ),
    )

    tasks = SpecCompiler().compile(spec)

    assert [task.id for task in tasks] == ["spec", "impl"]
    assert tasks[1].dependencies == ["spec"]
    assert tasks[1].risk == "medium"
    assert tasks[1].acceptance[0].description == "GET /health returns 200"


def test_rejects_cycle():
    spec = FactorySpec(
        goal="bad graph",
        tasks=(
            TaskSpec(id="a", title="A", goal="A", dependencies=("b",)),
            TaskSpec(id="b", title="B", goal="B", dependencies=("a",)),
        ),
    )

    with pytest.raises(SpecValidationError, match="cycle"):
        SpecCompiler().compile(spec)


def test_rejects_unknown_dependency():
    spec = FactorySpec(
        goal="bad graph",
        tasks=(
            TaskSpec(id="a", title="A", goal="A", dependencies=("missing",)),
        ),
    )

    with pytest.raises(SpecValidationError, match="unknown dependency"):
        SpecCompiler().compile(spec)


def test_rejects_invalid_risk():
    spec = FactorySpec(
        goal="bad risk",
        tasks=(TaskSpec(id="a", title="A", goal="A", risk="extreme"),),
    )

    with pytest.raises(SpecValidationError, match="unsupported risk"):
        SpecCompiler().compile(spec)

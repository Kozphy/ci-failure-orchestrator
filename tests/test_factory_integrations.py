from __future__ import annotations

from dataclasses import dataclass

import pytest

from ci_failure_orchestrator.ci_adapters import CIState
from ci_failure_orchestrator.factory_integrations import (
    CircleCIAdapter,
    GitHubActionsAdapter,
    JsonlEvidenceStore,
    ModelGoalSpecProvider,
    ProviderCLIRuntime,
)
from ci_failure_orchestrator.factory_runtime import EvidenceRecord, GoalRequest
from ci_failure_orchestrator.provider_adapters import ProviderRegistry, ProviderRun, ProviderSpec
from ci_failure_orchestrator.software_factory import AcceptanceCriterion, FactoryTask


class FakeModel:
    def generate_json(self, *, goal: str, context: str):
        return {
            "goal": goal,
            "tasks": [
                {
                    "id": "build",
                    "title": "Build",
                    "goal": f"Implement {context}",
                    "acceptance": ["tests pass"],
                    "risk": "low",
                },
                {
                    "id": "verify",
                    "title": "Verify",
                    "goal": "Verify independently",
                    "acceptance": ["verification passes"],
                    "dependencies": ["build"],
                },
            ],
        }


def test_model_goal_spec_provider_returns_machine_readable_spec() -> None:
    provider = ModelGoalSpecProvider(FakeModel())

    spec = provider.generate(GoalRequest(goal="Ship feature", context="API"))

    assert spec.goal == "Ship feature"
    assert [task.id for task in spec.tasks] == ["build", "verify"]
    assert spec.tasks[1].dependencies == ("build",)


def test_model_goal_spec_provider_rejects_non_sequence_tasks() -> None:
    class BadModel:
        def generate_json(self, *, goal: str, context: str):
            return {"goal": goal, "tasks": "not-a-task-list"}

    with pytest.raises(ValueError, match="tasks sequence"):
        ModelGoalSpecProvider(BadModel()).generate(GoalRequest(goal="x"))


@dataclass
class FakeRunner:
    returncode: int = 0
    prompts: list[str] | None = None

    def __post_init__(self) -> None:
        self.prompts = []

    def run(self, spec, *, prompt, repo_path=None):
        assert self.prompts is not None
        self.prompts.append(prompt)
        return ProviderRun(
            provider=spec.name,
            returncode=self.returncode,
            stdout="ok" if self.returncode == 0 else "",
            stderr="" if self.returncode == 0 else "boom",
            latency_ms=1.0,
            command=spec.argv,
            sandbox="/tmp/factory",
        )


def test_provider_cli_runtime_builds_normalized_agent_prompt() -> None:
    runner = FakeRunner()
    runtime = ProviderCLIRuntime(
        provider="codex",
        registry=ProviderRegistry([ProviderSpec(name="codex", argv=("codex",))]),
        runner=runner,
    )
    task = FactoryTask(
        id="T1",
        title="Implement",
        goal="Add health endpoint",
        acceptance=[AcceptanceCriterion("pytest passes")],
    )

    runtime.execute(task)

    assert runner.prompts is not None
    assert "Task ID: T1" in runner.prompts[0]
    assert "pytest passes" in runner.prompts[0]


def test_provider_cli_runtime_fails_closed_on_agent_error() -> None:
    runtime = ProviderCLIRuntime(
        provider="codex",
        registry=ProviderRegistry([ProviderSpec(name="codex", argv=("codex",))]),
        runner=FakeRunner(returncode=2),
    )

    with pytest.raises(RuntimeError, match="codex task T1 failed"):
        runtime.execute(FactoryTask(id="T1", title="x", goal="x"))


def test_jsonl_evidence_store_persists_across_instances(tmp_path) -> None:
    path = tmp_path / "factory-evidence.jsonl"
    first = JsonlEvidenceStore(path)
    first.append(
        EvidenceRecord(
            task_id="build",
            attempt=1,
            passed=False,
            failures=("pytest failed",),
        )
    )
    first.append(
        EvidenceRecord(
            task_id="build",
            attempt=2,
            passed=True,
            evidence=("pytest passed",),
        )
    )

    second = JsonlEvidenceStore(path)
    records = second.list("build")

    assert [record.attempt for record in records] == [1, 2]
    assert [record.passed for record in records] == [False, True]


class FakeCITransport:
    def trigger(self, provider: str, ref: str):
        return {"id": "101", "status": "queued", "html_url": f"https://ci/{provider}/101"}

    def status(self, provider: str, run_id: str):
        key = "state" if provider == "circleci" else "conclusion"
        return {"id": run_id, key: "success", "web_url": f"https://ci/{provider}/{run_id}"}

    def logs(self, provider: str, run_id: str) -> str:
        return f"{provider}:{run_id}:logs"

    def retry_failed(self, provider: str, run_id: str):
        return {"run_id": f"{run_id}-retry", "status": "running"}


@pytest.mark.parametrize("adapter_cls", [GitHubActionsAdapter, CircleCIAdapter])
def test_ci_adapters_share_one_factory_contract(adapter_cls) -> None:
    adapter = adapter_cls(FakeCITransport())

    triggered = adapter.trigger("feature/test")
    completed = adapter.status(triggered.run_id)
    retried = adapter.retry_failed(triggered.run_id)

    assert triggered.state is CIState.PENDING
    assert completed.state is CIState.PASSED
    assert retried.state is CIState.RUNNING
    assert adapter.logs(triggered.run_id).text.endswith(":101:logs")

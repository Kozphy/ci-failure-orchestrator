from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .ci_adapters import CIAdapter, CILog, CIRun, CIState
from .factory_runtime import EvidenceRecord, EvidenceStore, GoalRequest, GoalSpecProvider
from .provider_adapters import ProviderRegistry, SandboxRunner
from .software_factory import FactoryTask
from .spec_engine import FactorySpec, TaskSpec


class StructuredSpecModel(Protocol):
    """Model boundary for Goal -> structured spec generation.

    Implementations can call Codex, Claude, Gemini, or another model. The model
    is never trusted to execute directly: its output is parsed into FactorySpec
    and then validated by SpecCompiler before autonomous work begins.
    """

    def generate_json(self, *, goal: str, context: str) -> Mapping[str, Any]: ...


@dataclass
class ModelGoalSpecProvider(GoalSpecProvider):
    model: StructuredSpecModel

    def generate(self, request: GoalRequest) -> FactorySpec:
        payload = self.model.generate_json(goal=request.goal, context=request.context)
        tasks_payload = payload.get("tasks")
        if not isinstance(tasks_payload, Sequence) or isinstance(tasks_payload, (str, bytes)):
            raise ValueError("model spec must contain a tasks sequence")

        tasks: list[TaskSpec] = []
        for item in tasks_payload:
            if not isinstance(item, Mapping):
                raise ValueError("each model task must be an object")
            tasks.append(
                TaskSpec(
                    id=str(item.get("id", "")),
                    title=str(item.get("title", "")),
                    goal=str(item.get("goal", "")),
                    acceptance=tuple(str(value) for value in item.get("acceptance", ())),
                    dependencies=tuple(str(value) for value in item.get("dependencies", ())),
                    risk=str(item.get("risk", "low")),
                )
            )

        return FactorySpec(goal=str(payload.get("goal") or request.goal), tasks=tuple(tasks))


@dataclass
class ProviderCLIRuntime:
    """Execute normalized factory tasks through an existing sandboxed CLI provider."""

    provider: str
    registry: ProviderRegistry
    runner: SandboxRunner
    repo_path: str | Path | None = None

    def execute(self, task: FactoryTask) -> None:
        spec = self.registry.get(self.provider)
        acceptance = "\n".join(f"- {item.description}" for item in task.acceptance if item.required)
        prompt = (
            "You are an autonomous software-engineering worker.\n"
            f"Task ID: {task.id}\n"
            f"Goal: {task.goal}\n"
            "Acceptance criteria:\n"
            f"{acceptance or '- no explicit acceptance criteria'}\n"
            "Do not weaken tests or acceptance criteria. Make the smallest valid change."
        )
        result = self.runner.run(spec, prompt=prompt, repo_path=self.repo_path)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "provider failed"
            raise RuntimeError(f"{self.provider} task {task.id} failed: {detail}")


@dataclass
class JsonlEvidenceStore(EvidenceStore):
    """Durable append-only evidence store suitable for CI artifacts and audit."""

    path: Path

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, record: EvidenceRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def list(self, task_id: str | None = None) -> list[EvidenceRecord]:
        if not self.path.exists():
            return []
        records: list[EvidenceRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            record = EvidenceRecord(
                task_id=str(payload["task_id"]),
                attempt=int(payload["attempt"]),
                passed=bool(payload["passed"]),
                evidence=tuple(payload.get("evidence", ())),
                failures=tuple(payload.get("failures", ())),
            )
            if task_id is None or record.task_id == task_id:
                records.append(record)
        return records


class CITransport(Protocol):
    def trigger(self, provider: str, ref: str) -> Mapping[str, Any]: ...
    def status(self, provider: str, run_id: str) -> Mapping[str, Any]: ...
    def logs(self, provider: str, run_id: str) -> str: ...
    def retry_failed(self, provider: str, run_id: str) -> Mapping[str, Any]: ...


def _ci_state(payload: Mapping[str, Any]) -> CIState:
    raw = str(payload.get("conclusion") or payload.get("state") or payload.get("status") or "pending").lower()
    if raw in {"queued", "pending", "created"}:
        return CIState.PENDING
    if raw in {"in_progress", "running"}:
        return CIState.RUNNING
    if raw in {"success", "passed"}:
        return CIState.PASSED
    if raw in {"failure", "failed", "error"}:
        return CIState.FAILED
    if raw in {"cancelled", "canceled"}:
        return CIState.CANCELLED
    raise ValueError(f"unsupported CI state: {raw}")


@dataclass
class TransportCIAdapter(CIAdapter):
    """Concrete adapter shared by GitHub Actions and CircleCI transports."""

    provider: str
    transport: CITransport

    def trigger(self, ref: str) -> CIRun:
        return self._run(self.transport.trigger(self.provider, ref))

    def status(self, run_id: str) -> CIRun:
        return self._run(self.transport.status(self.provider, run_id))

    def logs(self, run_id: str) -> CILog:
        return CILog(run_id=run_id, text=self.transport.logs(self.provider, run_id))

    def retry_failed(self, run_id: str) -> CIRun:
        return self._run(self.transport.retry_failed(self.provider, run_id))

    def _run(self, payload: Mapping[str, Any]) -> CIRun:
        run_id = payload.get("id") or payload.get("run_id") or payload.get("pipeline_id")
        if run_id is None:
            raise ValueError("CI response is missing a run identifier")
        return CIRun(
            provider=self.provider,
            run_id=str(run_id),
            state=_ci_state(payload),
            url=str(payload.get("html_url") or payload.get("web_url") or payload.get("url") or ""),
        )


class GitHubActionsAdapter(TransportCIAdapter):
    def __init__(self, transport: CITransport) -> None:
        super().__init__(provider="github-actions", transport=transport)


class CircleCIAdapter(TransportCIAdapter):
    def __init__(self, transport: CITransport) -> None:
        super().__init__(provider="circleci", transport=transport)

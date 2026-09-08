"""Provider, evidence, and CI integration adapters for the software factory.

External systems are deliberately kept behind narrow contracts. Model output
is parsed into structured specs, agent CLIs execute through the existing
sandbox runner, evaluator decisions can be persisted as append-only JSONL, and
CI vendors are normalized behind one transport-facing adapter surface.
"""

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
    """Model boundary for generating a structured Goal -> FactorySpec proposal.

    Implementations can call Codex, Claude, Gemini, or another model. Returned
    mappings are untrusted until converted to :class:`FactorySpec` and checked
    by the deterministic :class:`SpecCompiler` in the runtime layer.
    """

    def generate_json(self, *, goal: str, context: str) -> Mapping[str, Any]:
        """Return a JSON-like mapping containing a goal and task sequence."""
        ...


@dataclass
class ModelGoalSpecProvider(GoalSpecProvider):
    """Convert structured model output into the factory's typed spec model."""

    model: StructuredSpecModel

    def generate(self, request: GoalRequest) -> FactorySpec:
        """Generate a typed candidate spec while rejecting malformed task data.

        Raises:
            ValueError: If ``tasks`` is not a sequence of mapping objects.
        """
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
    """Execute normalized factory tasks through a sandboxed CLI provider.

    The worker receives task intent and acceptance criteria, but it does not
    receive authority to weaken those criteria or decide that its own output is
    correct. Non-zero provider exits fail closed and are surfaced to the factory.
    """

    provider: str
    registry: ProviderRegistry
    runner: SandboxRunner
    repo_path: str | Path | None = None

    def execute(self, task: FactoryTask) -> None:
        """Run one task through the selected provider or raise on provider failure."""
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
    """Durable append-only evaluator evidence suitable for CI and audit use.

    Each line contains one immutable task-attempt decision. Reopening the store
    reconstructs typed :class:`EvidenceRecord` values, making evidence survive
    process restarts without introducing a database dependency.
    """

    path: Path

    def __init__(self, path: str | Path) -> None:
        """Bind the evidence store to a JSONL path."""
        self.path = Path(path)

    def append(self, record: EvidenceRecord) -> None:
        """Append one evaluator record, creating parent directories as needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def list(self, task_id: str | None = None) -> list[EvidenceRecord]:
        """Load all evidence or only records matching ``task_id``."""
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
    """Low-level transport contract for authenticated CI provider operations."""

    def trigger(self, provider: str, ref: str) -> Mapping[str, Any]:
        """Trigger a provider pipeline and return its raw normalized payload."""
        ...

    def status(self, provider: str, run_id: str) -> Mapping[str, Any]:
        """Fetch the latest raw status payload for a provider run."""
        ...

    def logs(self, provider: str, run_id: str) -> str:
        """Fetch diagnostic logs for a provider run."""
        ...

    def retry_failed(self, provider: str, run_id: str) -> Mapping[str, Any]:
        """Retry failed work and return the resulting provider payload."""
        ...


def _ci_state(payload: Mapping[str, Any]) -> CIState:
    """Normalize GitHub/CircleCI-style state fields into :class:`CIState`."""
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
    """Translate provider transport payloads into the stable CI adapter model."""

    provider: str
    transport: CITransport

    def trigger(self, ref: str) -> CIRun:
        """Trigger CI for ``ref`` and normalize the resulting run."""
        return self._run(self.transport.trigger(self.provider, ref))

    def status(self, run_id: str) -> CIRun:
        """Return the normalized status of ``run_id``."""
        return self._run(self.transport.status(self.provider, run_id))

    def logs(self, run_id: str) -> CILog:
        """Return normalized diagnostic logs for ``run_id``."""
        return CILog(run_id=run_id, text=self.transport.logs(self.provider, run_id))

    def retry_failed(self, run_id: str) -> CIRun:
        """Retry failed provider work and normalize the resulting run."""
        return self._run(self.transport.retry_failed(self.provider, run_id))

    def _run(self, payload: Mapping[str, Any]) -> CIRun:
        """Normalize one provider payload, failing if no run ID is present."""
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
    """Concrete factory CI adapter for GitHub Actions."""

    def __init__(self, transport: CITransport) -> None:
        """Bind a GitHub Actions transport to the normalized CI contract."""
        super().__init__(provider="github-actions", transport=transport)


class CircleCIAdapter(TransportCIAdapter):
    """Concrete factory CI adapter for CircleCI."""

    def __init__(self, transport: CITransport) -> None:
        """Bind a CircleCI transport to the normalized CI contract."""
        super().__init__(provider="circleci", transport=transport)

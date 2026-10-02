"""Task / Run / Attempt records for the service path.

A Task is the objective: one CI failure in one repository. Each fix-repo invocation is a
Run of a task (the foundation run, keyed by ``run_id``; its durable state is unchanged).
Each proposal checked in a worktree is an Attempt, attributed to the agent that produced it.

Layout under the artifacts root::

    tasks/<task_id>/task.json        immutable objective
    tasks/<task_id>/runs.jsonl       append-only, one line per finished run
    runs/<run_id>/fix-repo/attempt-NNN.json
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..foundation.durable import atomic_write_text, canonical_json, sanitize_value
from ..foundation.models import new_id, utc_now
from ..foundation.persistence import FileEvidenceStore
from .common import FIX_DIR

TASK_SCHEMA = "service.task.v1"
ATTEMPT_SCHEMA = "service.attempt.v1"
TASKS_DIR = "tasks"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class AttemptStatus(str, Enum):
    NO_PATCH = "NO_PATCH"
    REFUSED = "REFUSED"
    PATCH_REJECTED = "PATCH_REJECTED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFIED = "VERIFIED"


@dataclass(frozen=True)
class Task:
    task_id: str
    repository: str
    trigger: str
    objective: str
    created_at: str = field(default_factory=utc_now)
    schema_version: str = TASK_SCHEMA


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    task_id: str
    run_id: str
    number: int
    agent: str
    proposal_source: str
    status: AttemptStatus
    error: str | None
    patch_sha256: str | None
    files_changed: tuple[str, ...]
    started_at: str
    completed_at: str
    duration_ms: int
    schema_version: str = ATTEMPT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["files_changed"] = list(self.files_changed)
        return data


def attempt_name(number: int) -> str:
    return f"attempt-{number:03d}.json"


def write_attempt(artifacts_root: Path, attempt: Attempt) -> None:
    FileEvidenceStore(artifacts_root).write_json(
        attempt.run_id, FIX_DIR, attempt.to_dict(), name=attempt_name(attempt.number)
    )


def read_attempts(artifacts_root: Path, run_id: str) -> list[dict[str, Any]]:
    fix_root = Path(artifacts_root) / "runs" / run_id / FIX_DIR
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(fix_root.glob("attempt-[0-9][0-9][0-9].json"))
    ]


class TaskStore:
    """File-backed task records; ``runs.jsonl`` is append-only."""

    def __init__(self, artifacts_root: Path) -> None:
        self.root = Path(artifacts_root) / TASKS_DIR

    def _dir(self, task_id: str) -> Path:
        if not _ID_RE.match(task_id or ""):
            raise ValueError(f"invalid task id: {task_id!r}")
        return self.root / task_id

    def create(self, *, repository: str, trigger: str, objective: str) -> Task:
        task = Task(task_id=new_id("task"), repository=repository, trigger=trigger, objective=objective)
        atomic_write_text(self._dir(task.task_id) / "task.json", canonical_json(sanitize_value(asdict(task))))
        return task

    def load(self, task_id: str) -> Task:
        path = self._dir(task_id) / "task.json"
        if not path.is_file():
            raise ValueError(f"unknown task: {task_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != TASK_SCHEMA:
            raise ValueError(f"unsupported task schema: {data.get('schema_version')}")
        return Task(**data)

    def append_run(self, task_id: str, entry: dict[str, Any]) -> None:
        path = self._dir(task_id) / "runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(sanitize_value(entry), sort_keys=True, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def runs(self, task_id: str) -> list[dict[str, Any]]:
        path = self._dir(task_id) / "runs.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def task_summary(artifacts_root: Path, task_id: str) -> dict[str, Any]:
    store = TaskStore(artifacts_root)
    task = store.load(task_id)
    runs = [
        {**run, "attempts": read_attempts(artifacts_root, str(run.get("run_id") or ""))}
        for run in store.runs(task_id)
    ]
    return {"task": asdict(task), "runs": runs}

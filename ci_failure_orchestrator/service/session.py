"""Per-run state shared by the prompt builder, proposal factory and sandbox."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..patch_sandbox import VerificationStep


@dataclass(frozen=True)
class VerifyCommand:
    """Immutable verification command: a step name, its display string and its argv."""

    name: str
    display: str
    argv: tuple[str, ...]


@dataclass
class FixSession:
    """Mutable state of one fix-repo run, including feedback from earlier attempts."""

    repo: Path
    base_commit: str
    commands: tuple[VerifyCommand, ...]
    failure: dict[str, Any]
    baseline: tuple[VerificationStep, ...]
    tracked_files: tuple[str, ...]
    artifacts_root: Path
    task_id: str = ""
    proposal_source: str = ""
    agent: str = ""
    feedback: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None
    attempt_started_at: str = ""
    attempt_started_clock: float = 0.0

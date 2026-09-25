"""Per-run state shared by the prompt builder, proposal factory and sandbox."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..patch_sandbox import VerificationStep


@dataclass(frozen=True)
class VerifyCommand:
    name: str
    display: str
    argv: tuple[str, ...]


@dataclass
class FixSession:
    repo: Path
    base_commit: str
    commands: tuple[VerifyCommand, ...]
    failure: dict[str, Any]
    baseline: tuple[VerificationStep, ...]
    tracked_files: tuple[str, ...]
    artifacts_root: Path
    feedback: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None

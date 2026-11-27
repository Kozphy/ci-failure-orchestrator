"""Deterministic, fail-closed scope gate for agent-generated changes.

This module does not execute agent code or confer approval to merge, push or deploy.
Decisions must be produced by a trusted host, using a trusted task contract and
the actual diff paths, never an agent-provided summary of its changes.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable

# Never allow a coding agent to change the controls used to approve its work.
DEFAULT_PROTECTED = (
    ".github/**",
    ".git/**",
    "**/.git/**",
    "**/CODEOWNERS",
    "**/.env",
    "**/.env.*",
    "**/*secret*",
    "**/*credential*",
    "ci_failure_orchestrator/governed_agent/**",
    "ci_failure_orchestrator/foundation/policy*.py",
    "ci_failure_orchestrator/foundation/audit*.py",
    "pyproject.toml",
    "pytest.ini",
    "tox.ini",
    "requirements*.txt",
    "tests/**",
)


@dataclass(frozen=True)
class TaskContract:
    """Trusted host-issued task scope and bounded execution limits."""

    task_id: str
    allowed_paths: tuple[str, ...]
    acceptance_commands: tuple[str, ...]
    max_attempts: int = 3
    max_changed_files: int = 10

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id is required")
        if not self.allowed_paths or not all(_safe_pattern(p) for p in self.allowed_paths):
            raise ValueError("allowed_paths must contain safe repository-relative patterns")
        if not self.acceptance_commands or not all(c.strip() for c in self.acceptance_commands):
            raise ValueError("acceptance_commands must be nonempty")
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if not 1 <= self.max_changed_files <= 100:
            raise ValueError("max_changed_files must be between 1 and 100")


@dataclass(frozen=True)
class ContractDecision:
    """Immutable scope decision; approval of the full task requires other gates."""

    allowed: bool
    reasons: tuple[str, ...]
    checked_paths: tuple[str, ...]


def _safe_pattern(value: str) -> bool:
    if not value or value != value.strip() or "\\" in value or value.startswith("/"):
        return False
    parts = value.split("/")
    return all(part not in ("", ".", "..") for part in parts) and not value.startswith("~")


def _safe_path(value: str) -> bool:
    if not _safe_pattern(value) or any(c in value for c in "*?[]"):
        return False
    return PurePosixPath(value).as_posix() == value


def _matches(path: str, pattern: str) -> bool:
    # Pattern matches whole paths. Patterns ending in /** include descendants.
    if pattern.endswith("/**") and path.startswith(pattern[:-3] + "/"):
        return True
    return fnmatch.fnmatchcase(path, pattern)


def validate_changes(
    contract: TaskContract,
    changed_paths: Iterable[str],
    *,
    attempt: int,
    protected_paths: tuple[str, ...] = DEFAULT_PROTECTED,
) -> ContractDecision:
    """Reject unauthorized, unsafe, protected or over-budget changes.

    changed_paths must come from a trusted VCS diff. This check covers names
    only: the caller must separately reject symlinks, unsafe commands, failing
    tests, altered test semantics, missing evidence, and unauthorized network.
    """
    paths = tuple(changed_paths)
    reasons: list[str] = []
    if not 1 <= attempt <= contract.max_attempts:
        reasons.append("attempt_budget_exceeded")
    if not paths:
        reasons.append("missing_diff_evidence")
    if len(paths) != len(set(paths)):
        reasons.append("duplicate_changed_paths")
    if len(paths) > contract.max_changed_files:
        reasons.append("changed_file_budget_exceeded")
    for path in paths:
        if not _safe_path(path):
            reasons.append(f"unsafe_path:{path}")
            continue
        if any(_matches(path, pattern) for pattern in protected_paths):
            reasons.append(f"protected_path:{path}")
        elif not any(_matches(path, pattern) for pattern in contract.allowed_paths):
            reasons.append(f"outside_allowed_scope:{path}")
    return ContractDecision(allowed=not reasons, reasons=tuple(reasons), checked_paths=paths)

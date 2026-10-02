"""Reproduce-time detection of failures that a source patch cannot be shown to fix.

When the unpatched reproduction fails because a command, a third-party package or the
network is missing, a later "passing" patch would only prove that the patch worked around
the environment. Such runs escalate before any provider is called.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from ..patch_sandbox import VerificationStep
from .session import VerifyCommand
from .untrusted import clean_untrusted

MAX_EVIDENCE_CHARS = 200

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "missing_command",
        re.compile(
            r"command_not_runnable:|command not found|is not recognized as an internal or external command",
            re.IGNORECASE,
        ),
    ),
    (
        "dependency_resolution",
        re.compile(
            r"No matching distribution found|Could not find a version that satisfies the requirement"
            r"|ResolutionImpossible|npm ERR! code (?:E404|ERESOLVE|ETARGET)|failed to select a version"
            r"|go: [^\n]*unknown revision",
            re.IGNORECASE,
        ),
    ),
    (
        "network",
        re.compile(
            r"Could not resolve host|Temporary failure in name resolution|Name or service not known"
            r"|getaddrinfo (?:ENOTFOUND|EAI_AGAIN)|Network is unreachable|Failed to establish a new connection"
            r"|ECONNRESET|ETIMEDOUT|CERTIFICATE_VERIFY_FAILED",
            re.IGNORECASE,
        ),
    ),
    (
        "resource_exhaustion",
        re.compile(r"No space left on device|Cannot allocate memory", re.IGNORECASE),
    ),
)
_PY_MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([A-Za-z_][\w.]*)'")
_NODE_MISSING_MODULE = re.compile(r"Cannot find module '([^'./][^']*)'")
_KILLED_RETURN_CODES = frozenset({137, -9})


@dataclass(frozen=True)
class EnvironmentFinding:
    kind: str
    step: str
    command: str
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "step": self.step, "command": self.command, "evidence": self.evidence}


def repository_module_names(tracked_files: Iterable[str]) -> frozenset[str]:
    """Every directory and module stem in the tracked tree (``src/pkg/mod.py`` → src, pkg, mod)."""
    names: set[str] = set()
    for rel in tracked_files:
        parts = PurePosixPath(rel.replace("\\", "/")).parts
        names.update(parts[:-1])
        if parts:
            names.add(PurePosixPath(parts[-1]).stem)
    return frozenset(names)


def _evidence_line(output: str, start: int) -> str:
    line_start = output.rfind("\n", 0, start) + 1
    line_end = output.find("\n", start)
    line = output[line_start : line_end if line_end != -1 else len(output)]
    return clean_untrusted(line.strip())[:MAX_EVIDENCE_CHARS]


def _match(output: str, repo_modules: frozenset[str]) -> tuple[str, str] | None:
    for kind, pattern in _PATTERNS:
        found = pattern.search(output)
        if found:
            return kind, _evidence_line(output, found.start())
    for pattern in (_PY_MISSING_MODULE, _NODE_MISSING_MODULE):
        for found in pattern.finditer(output):
            top = re.split(r"[./]", found.group(1).lstrip("@"))[0]
            if top and top not in repo_modules:
                return "missing_dependency", _evidence_line(output, found.start())
    return None


def detect_environment_failure(
    baseline: Iterable[VerificationStep],
    commands: Iterable[VerifyCommand],
    tracked_files: Iterable[str],
) -> EnvironmentFinding | None:
    displays = {c.name: c.display for c in commands}
    repo_modules = repository_module_names(tracked_files)
    for step in baseline:
        if step.passed:
            continue
        command = clean_untrusted(displays.get(step.name, step.name))[:MAX_EVIDENCE_CHARS]
        if step.returncode in _KILLED_RETURN_CODES:
            return EnvironmentFinding("resource_exhaustion", step.name, command, f"exit code {step.returncode}")
        hit = _match(f"{step.stdout}\n{step.stderr}", repo_modules)
        if hit:
            return EnvironmentFinding(hit[0], step.name, command, hit[1])
    return None

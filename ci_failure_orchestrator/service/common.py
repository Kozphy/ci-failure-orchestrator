"""Shared constants and subprocess helpers for the service path."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

DEFAULT_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "TMP",
    "TEMP",
    "SYSTEMROOT",
    "PATHEXT",
    "COMSPEC",
    "APPDATA",
    "LOCALAPPDATA",
)

# Credentials and git/ssh indirection that would let a provider or repository code act
# on GitHub (push, merge, mint OIDC tokens). Never forwarded, even when requested.
BLOCKED_ENV_NAMES = frozenset(
    {
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITHUB_PAT",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "SSH_AUTH_SOCK",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        "GIT_CREDENTIAL_HELPER",
    }
)
BLOCKED_ENV_PREFIXES = ("ACTIONS_", "GIT_CONFIG")


def blocked_env_names(names: Sequence[str]) -> tuple[str, ...]:
    blocked: list[str] = []
    for name in names:
        upper = name.strip().upper()
        if (
            upper in BLOCKED_ENV_NAMES
            or upper.startswith(BLOCKED_ENV_PREFIXES)
            or upper.endswith(("_GITHUB_TOKEN", "_GH_TOKEN"))
        ):
            blocked.append(name)
    return tuple(blocked)


FIX_DIR = "fix-repo"
METADATA_NAME = "metadata.json"
FINAL_PATCH_NAME = "final.patch"

MAX_LOG_CHARS = 12_000
MAX_FEEDBACK_CHARS = 4_000


def split_command(command: str) -> tuple[str, ...]:
    """Split a command string into argv without shell interpretation.

    Quotes group words; backslashes are kept literally so Windows paths survive.
    The executable is resolved on PATH because commands run with ``shell=False``
    (e.g. ``npm`` -> ``npm.cmd`` on Windows).
    """

    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    argv = list(lexer)
    if not argv:
        raise ValueError("empty command")
    resolved = shutil.which(argv[0])
    if resolved:
        argv[0] = resolved
    return tuple(argv)


def git(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )


def tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[-limit:]

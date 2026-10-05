"""Proposal sources: an operator patch file or an external provider CLI."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..provider_adapters import ProviderSpec, SandboxRunner
from .common import DEFAULT_ENV_ALLOWLIST, blocked_env_names, tail
from .patches import decode_patch_bytes


@dataclass(frozen=True)
class GeneratedText:
    """Raw output of a proposal source, with an error code and detail on failure."""

    text: str
    error: str | None = None
    detail: str = ""


_INTERPRETERS = frozenset({"python", "python3", "py", "node", "bash", "sh", "pwsh", "powershell", "uv", "npx"})


def agent_label(argv: Sequence[str]) -> str:
    """Stable identity for a provider CLI: the executable, or the script an interpreter runs."""
    parts = [Path(arg).stem for arg in argv if arg and not arg.startswith("-")]
    if not parts:
        return "provider"
    if parts[0].lower() in _INTERPRETERS and len(parts) > 1:
        return parts[1]
    return parts[0]


class ProposalSource(Protocol):
    """Interface for anything that turns a repair prompt into candidate patch text."""

    name: str
    agent: str

    def generate(self, prompt: str, attempt_number: int) -> GeneratedText:
        """Return the source's response to the prompt for the given attempt."""
        ...


class PatchFileSource:
    """Returns the same operator-supplied patch on every attempt."""

    name = "patch-file"
    agent = "patch-file"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def generate(self, prompt: str, attempt_number: int) -> GeneratedText:
        """Return the decoded patch file, or a ``provider_failed`` result when it cannot be read."""
        try:
            return GeneratedText(decode_patch_bytes(self.path.read_bytes()))
        except OSError as exc:
            return GeneratedText("", "provider_failed", f"cannot read patch file: {exc}")


class ProviderCommandSource:
    """Runs an external CLI (prompt on stdin, empty temp cwd, env allowlist)."""

    name = "provider-cmd"

    def __init__(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int = 600,
        env_passthrough: Sequence[str] = (),
    ) -> None:
        blocked = blocked_env_names(env_passthrough)
        if blocked:
            raise ValueError(f"refusing to pass credential variables to the provider: {', '.join(blocked)}")
        self.agent = agent_label(argv)
        self.spec = ProviderSpec(
            name="fix-repo-provider",
            argv=tuple(argv),
            timeout_seconds=timeout_seconds,
            max_output_chars=200_000,
        )
        self.runner = SandboxRunner(env_allowlist=DEFAULT_ENV_ALLOWLIST + tuple(env_passthrough))

    def generate(self, prompt: str, attempt_number: int) -> GeneratedText:
        """Run the provider CLI with the prompt on stdin; a non-zero exit yields ``provider_failed``."""
        run = self.runner.run(self.spec, prompt=prompt)
        if run.returncode != 0:
            return GeneratedText(run.stdout, "provider_failed", tail(run.stderr, 2_000))
        return GeneratedText(run.stdout)

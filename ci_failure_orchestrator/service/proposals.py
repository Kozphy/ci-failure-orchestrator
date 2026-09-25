"""Proposal sources: an operator patch file or an external provider CLI."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..provider_adapters import ProviderSpec, SandboxRunner
from .common import DEFAULT_ENV_ALLOWLIST, tail
from .patches import decode_patch_bytes


@dataclass(frozen=True)
class GeneratedText:
    text: str
    error: str | None = None
    detail: str = ""


class ProposalSource(Protocol):
    name: str

    def generate(self, prompt: str, attempt_number: int) -> GeneratedText: ...


class PatchFileSource:
    """Returns the same operator-supplied patch on every attempt."""

    name = "patch-file"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def generate(self, prompt: str, attempt_number: int) -> GeneratedText:
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
        self.spec = ProviderSpec(
            name="fix-repo-provider",
            argv=tuple(argv),
            timeout_seconds=timeout_seconds,
            max_output_chars=200_000,
        )
        self.runner = SandboxRunner(env_allowlist=DEFAULT_ENV_ALLOWLIST + tuple(env_passthrough))

    def generate(self, prompt: str, attempt_number: int) -> GeneratedText:
        run = self.runner.run(self.spec, prompt=prompt)
        if run.returncode != 0:
            return GeneratedText(run.stdout, "provider_failed", tail(run.stderr, 2_000))
        return GeneratedText(run.stdout)

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ProviderRun:
    provider: str
    returncode: int
    stdout: str
    stderr: str
    latency_ms: float
    command: tuple[str, ...]
    sandbox: str


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: int = 120
    max_output_chars: int = 20_000

    @classmethod
    def from_env(cls, name: str, env_var: str, *, timeout_seconds: int = 120) -> "ProviderSpec":
        raw = os.getenv(env_var, "").strip()
        if not raw:
            raise ValueError(f"{env_var} is not configured")
        return cls(name=name, argv=tuple(shlex.split(raw)), timeout_seconds=timeout_seconds)


class SandboxRunner:
    """Runs provider CLIs in an isolated temporary workspace.

    The runner is intentionally fail-closed: shell execution is disabled,
    the provider receives only an explicit environment allowlist, and each run
    has a timeout plus bounded captured output.
    """

    def __init__(
        self,
        *,
        env_allowlist: Sequence[str] = ("PATH", "HOME", "USERPROFILE", "TMP", "TEMP"),
    ) -> None:
        self.env_allowlist = tuple(env_allowlist)

    def run(
        self,
        spec: ProviderSpec,
        *,
        prompt: str,
        repo_path: str | Path | None = None,
        extra_env: Mapping[str, str] | None = None,
    ) -> ProviderRun:
        env = {key: os.environ[key] for key in self.env_allowlist if key in os.environ}
        if extra_env:
            env.update(extra_env)

        with tempfile.TemporaryDirectory(prefix=f"ci-orchestrator-{spec.name}-") as sandbox:
            sandbox_path = Path(sandbox)
            if repo_path is not None:
                (sandbox_path / "REPO_PATH.txt").write_text(str(Path(repo_path).resolve()), encoding="utf-8")

            started = perf_counter()
            try:
                completed = subprocess.run(
                    list(spec.argv),
                    input=prompt,
                    cwd=sandbox_path,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=spec.timeout_seconds,
                    shell=False,
                    check=False,
                )
                latency_ms = (perf_counter() - started) * 1000.0
                return ProviderRun(
                    provider=spec.name,
                    returncode=completed.returncode,
                    stdout=completed.stdout[-spec.max_output_chars :],
                    stderr=completed.stderr[-spec.max_output_chars :],
                    latency_ms=latency_ms,
                    command=spec.argv,
                    sandbox=str(sandbox_path),
                )
            except subprocess.TimeoutExpired as exc:
                latency_ms = (perf_counter() - started) * 1000.0
                stdout = exc.stdout if isinstance(exc.stdout, str) else ""
                stderr = exc.stderr if isinstance(exc.stderr, str) else ""
                return ProviderRun(
                    provider=spec.name,
                    returncode=124,
                    stdout=stdout[-spec.max_output_chars :],
                    stderr=(stderr + "\nprovider_timeout")[-spec.max_output_chars :],
                    latency_ms=latency_ms,
                    command=spec.argv,
                    sandbox=str(sandbox_path),
                )


class ProviderRegistry:
    """Provider-neutral registry for Cursor, Claude, Codex, Gemini, or custom CLIs."""

    def __init__(self, specs: Sequence[ProviderSpec]) -> None:
        self._specs = {spec.name: spec for spec in specs}

    def get(self, name: str) -> ProviderSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise KeyError(f"unknown provider: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))


def default_registry_from_env() -> ProviderRegistry:
    """Load enabled provider CLI commands from environment variables.

    Values are full argv command strings. Prompts are always sent on stdin,
    avoiding prompt-in-argv problems on Windows shells.
    """
    mapping = {
        "cursor": "CI_ORCHESTRATOR_CURSOR_CMD",
        "claude": "CI_ORCHESTRATOR_CLAUDE_CMD",
        "codex": "CI_ORCHESTRATOR_CODEX_CMD",
        "gemini": "CI_ORCHESTRATOR_GEMINI_CMD",
    }
    specs: list[ProviderSpec] = []
    for name, env_var in mapping.items():
        if os.getenv(env_var, "").strip():
            specs.append(ProviderSpec.from_env(name, env_var))
    return ProviderRegistry(specs)

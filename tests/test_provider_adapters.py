from __future__ import annotations

import sys

import pytest

from ci_failure_orchestrator.provider_adapters import (
    ProviderRegistry,
    ProviderSpec,
    SandboxRunner,
)


def test_prompt_is_sent_on_stdin_not_argv() -> None:
    spec = ProviderSpec(
        name="fake",
        argv=(sys.executable, "-c", "import sys; print(sys.stdin.read())"),
        timeout_seconds=5,
    )
    result = SandboxRunner().run(spec, prompt="repair this failure")
    assert result.returncode == 0
    assert result.stdout.strip() == "repair this failure"
    assert "repair this failure" not in result.command


def test_provider_nonzero_exit_is_observable() -> None:
    spec = ProviderSpec(
        name="fake",
        argv=(sys.executable, "-c", "import sys; print('bad', file=sys.stderr); raise SystemExit(7)"),
        timeout_seconds=5,
    )
    result = SandboxRunner().run(spec, prompt="x")
    assert result.returncode == 7
    assert "bad" in result.stderr
    assert result.latency_ms >= 0


def test_output_is_bounded() -> None:
    spec = ProviderSpec(
        name="fake",
        argv=(sys.executable, "-c", "print('x' * 200)"),
        max_output_chars=25,
    )
    result = SandboxRunner().run(spec, prompt="x")
    assert len(result.stdout) <= 25


def test_registry_is_provider_neutral() -> None:
    registry = ProviderRegistry(
        [
            ProviderSpec("cursor", ("cursor-agent",)),
            ProviderSpec("claude", ("claude",)),
            ProviderSpec("codex", ("codex",)),
            ProviderSpec("gemini", ("gemini",)),
        ]
    )
    assert registry.names() == ("claude", "codex", "cursor", "gemini")
    assert registry.get("codex").name == "codex"
    with pytest.raises(KeyError):
        registry.get("unknown")

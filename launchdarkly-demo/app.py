"""Minimal LaunchDarkly onboarding demo (isolated from product CLIs)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

FLAG_KEY = "sample-welcome-banner"
FLAG_URL = (
    "https://app.launchdarkly.com/projects/default/flags/"
    f"{FLAG_KEY}/targeting?env=test"
)
BANNER_ON = "=== LaunchDarkly test banner (flag is on) ==="
BANNER_OFF = "--- LaunchDarkly test banner (flag is off) ---"


@dataclass(frozen=True)
class BannerResult:
    """Outcome of one demo evaluation."""

    enabled: bool
    source: str  # "flag" | "missing_key" | "init_failed" | "fallback"
    lines: tuple[str, ...]
    exit_code: int


class FlagClient(Protocol):
    """Minimal client surface used by the demo."""

    def is_initialized(self) -> bool: ...

    def variation(self, key: str, context: object, default: bool) -> bool: ...

    def flush(self) -> None: ...


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def load_sdk_key_from_env(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    return (env.get("LAUNCHDARKLY_SDK_KEY") or "").strip()


def render_banner(enabled: bool, *, hint_url: bool = True) -> tuple[str, ...]:
    if enabled:
        return (
            BANNER_ON,
            "Flag is ON. Turn it off in LaunchDarkly to see the off state.",
        )
    lines = [
        BANNER_OFF,
        "Flag is OFF. Turn it on here:" if hint_url else "Flag is OFF (safe fallback).",
    ]
    if hint_url:
        lines.append(FLAG_URL)
    return tuple(lines)


def evaluate_banner(
    *,
    sdk_key: str,
    client: FlagClient | None,
    flag_key: str = FLAG_KEY,
    context: object | None = None,
) -> BannerResult:
    """Evaluate the demo flag with safe defaults on missing key / init failure."""
    if not sdk_key:
        lines = (
            "LAUNCHDARKLY_SDK_KEY is not set. Copy launchdarkly-demo/env.example "
            "values into the repo-root .env file.",
            *render_banner(False, hint_url=False),
        )
        return BannerResult(False, "missing_key", lines, 1)

    if client is None or not client.is_initialized():
        lines = (
            "LaunchDarkly client failed to initialize; using safe OFF fallback.",
            *render_banner(False, hint_url=False),
        )
        return BannerResult(False, "init_failed", lines, 0)

    try:
        enabled = bool(client.variation(flag_key, context, False))
    except Exception:  # noqa: BLE001 — demo must never crash on evaluation errors
        lines = (
            "Flag evaluation failed; using safe OFF fallback.",
            *render_banner(False, hint_url=False),
        )
        return BannerResult(False, "fallback", lines, 0)

    return BannerResult(enabled, "flag", render_banner(enabled), 0)


def build_live_client(sdk_key: str) -> FlagClient:
    import ldclient
    from ldclient.config import Config

    ldclient.set_config(Config(sdk_key))
    return ldclient.get()


def build_demo_context() -> object:
    from ldclient import Context

    return Context.builder("demo-user").name("Demo").build()


def main(argv: list[str] | None = None) -> int:
    del argv  # reserved for future CLI options
    repo_root = Path(__file__).resolve().parents[1]
    _load_dotenv(repo_root / ".env")
    _load_dotenv(Path(__file__).resolve().parent / ".env")

    sdk_key = load_sdk_key_from_env()
    client: FlagClient | None = None
    context: object | None = None
    if sdk_key:
        try:
            client = build_live_client(sdk_key)
            context = build_demo_context()
        except Exception:  # noqa: BLE001 — treat construction failure as init_failed
            client = None

    result = evaluate_banner(sdk_key=sdk_key, client=client, context=context)
    stream = sys.stderr if result.source == "missing_key" else sys.stdout
    for line in result.lines:
        print(line, file=stream)

    if client is not None and result.source == "flag":
        try:
            client.flush()
        except Exception:  # noqa: BLE001
            pass
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

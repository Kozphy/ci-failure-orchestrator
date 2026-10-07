"""Experiment manifest: everything needed to reproduce or audit a run, and no secrets.

Secret handling: config values are passed through ``ci_failure_orchestrator.audit.redact`` (sensitive
keys and ``key=value`` shapes) plus token-shape patterns below. Environment variable values are never
recorded; only the names of variables a provider is allowed to see.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
from importlib import metadata
from pathlib import Path
from typing import Any

from ci_failure_orchestrator.audit import redact

from .paths import ROOT

MANIFEST_SCHEMA = "research-experiment-manifest/v1"
_TOKEN_SHAPES = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
)
_PACKAGES = ("ci-failure-orchestrator", "PyYAML", "pytest")


def scrub(value: Any) -> Any:
    """Redact sensitive keys and token-shaped strings from a JSON-like value."""
    value = redact(value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        for pattern in _TOKEN_SHAPES:
            value = pattern.sub("[REDACTED]", value)
    return value


def contains_secret_shape(text: str) -> bool:
    """True when ``text`` contains a known credential shape (used by tests and the runner's final check)."""
    return any(p.search(text) for p in _TOKEN_SHAPES)


def git_state(root: Path = ROOT) -> dict[str, Any]:
    """Current commit and whether tracked files differ from it."""
    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain", "--untracked-files=no")
    return {"git_commit": commit, "git_dirty": bool(status) if status is not None else None}


def environment() -> dict[str, Any]:
    """Interpreter, platform and key package versions."""
    versions: dict[str, str | None] = {}
    for name in _PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": versions,
    }


def config_digest(config: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON form of the (unscrubbed) config."""
    return sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def utc_timestamp() -> str:
    """Current UTC time in ISO-8601 with seconds precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_manifest(
    *,
    experiment_id: str,
    timestamp: str,
    config: Mapping[str, Any],
    config_path: str | None,
    lock: Mapping[str, Any],
    splits: Sequence[str],
    case_ids: Mapping[str, Sequence[str]],
    systems: Mapping[str, Sequence[str]],
    system_versions: Mapping[str, str],
    prompts: Mapping[str, str],
    provider: Mapping[str, Any],
    command: Sequence[str],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the manifest. Every field is derived from inputs; nothing is measured here."""
    repair = config.get("repair") or {}
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "experiment_id": experiment_id,
        "timestamp": timestamp,
        **git_state(),
        "dataset_version": lock.get("dataset_version"),
        "dataset_sha256": lock.get("dataset_sha256"),
        "split_sha256": {name: (lock.get("splits") or {}).get(name, {}).get("sha256") for name in splits},
        "splits_evaluated": list(splits),
        "holdout_used": "holdout" in splits,
        "case_ids": {track: list(ids) for track, ids in case_ids.items()},
        "systems": {track: list(names) for track, names in systems.items()},
        "baseline_versions": dict(system_versions),
        "model": {
            "provider": provider.get("provider"),
            "name": provider.get("name"),
            "version": provider.get("version"),
            "temperature": provider.get("temperature"),
            "claim_eligible": provider.get("claim_eligible"),
            "env_passthrough_names": list(provider.get("env_passthrough") or []),
        },
        "prompt_versions": dict(prompts),
        "context_policy": (config.get("diagnosis") or {}).get("context_policy", "ctx-v1"),
        "seed": (config.get("experiment") or {}).get("seed"),
        "candidate_order_seed": repair.get("candidate_order_seed"),
        "retry_budget": repair.get("retry_budget"),
        "require_real_ci": bool(repair.get("require_real_ci", False)),
        "tool_permissions": {
            "repair_candidates": "scripted from the frozen dataset; no model generates patches",
            "product_execution": "run_fix_repo: disposable git worktrees, allowlisted environment, no shell",
            "model_outputs": "parsed as JSON data; never executed",
            "network": "not required; the command provider may use it if the operator's command does",
        },
        "environment": environment(),
        "command": " ".join(command),
        "config_path": config_path,
        "config_sha256": config_digest(config),
        "config": scrub(dict(config)),
    }
    if extra:
        manifest.update(scrub(dict(extra)))
    return manifest

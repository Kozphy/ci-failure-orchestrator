"""Audit completeness check shared by observability (avoids benchmark import cycles)."""

from __future__ import annotations

from pathlib import Path


def check_audit_artifacts(run_root: Path) -> tuple[bool, tuple[str, ...]]:
    """Minimum audit completeness: state.json + nonempty events.jsonl."""

    found: list[str] = []
    state = run_root / "state.json"
    events = run_root / "events.jsonl"
    if state.is_file():
        found.append("state.json")
    if events.is_file():
        found.append("events.jsonl")
        try:
            lines = [ln for ln in events.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if lines:
                found.append("events_nonempty")
        except OSError:
            pass
    complete = "state.json" in found and "events_nonempty" in found
    return complete, tuple(found)

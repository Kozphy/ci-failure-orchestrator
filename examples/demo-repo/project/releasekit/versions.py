"""Version helpers used by the release script."""

from __future__ import annotations

from collections.abc import Iterable


def parse_version(text: str) -> tuple[int, int, int]:
    """Parse ``"v1.2.3"`` or ``"1.2.3"`` into ``(1, 2, 3)``."""
    major, minor, patch = text.strip().removeprefix("v").split(".")
    return int(major), int(minor), int(patch)


def is_newer(candidate: str, current: str) -> bool:
    """Return True when ``candidate`` is a later release than ``current``."""
    return candidate.strip().removeprefix("v") > current.strip().removeprefix("v")


def latest(versions: Iterable[str]) -> str:
    """Return the newest version in ``versions``."""
    return max(versions, key=parse_version)


def next_release(current: str, part: str) -> str:
    """Bump ``part`` (major, minor or patch) of ``current`` and reset the lower parts."""
    major, minor, patch = parse_version(current)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown version part: {part}")

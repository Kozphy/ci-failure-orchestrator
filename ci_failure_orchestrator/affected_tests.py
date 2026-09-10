"""Affected test selection with explicit mapping and convention-based fallback.

This module provides conservative targeted test selection from changed source paths.
It supports explicit mapping for production use and a convention-based fallback for
standard project layouts (src/pkg/mod.py -> tests/pkg/test_mod.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable


@dataclass(frozen=True)
class TestSelection:
    """Result from affected test selection.

    Attributes:
        changed_files: Tuple of changed file paths that were analyzed.
        selected_tests: Tuple of selected test paths.
        fallback_to_full_suite: Whether the caller should run the full suite instead.
        reason: Human-readable explanation of the selection decision.
    """

    changed_files: tuple[str, ...]
    selected_tests: tuple[str, ...]
    fallback_to_full_suite: bool
    reason: str


def select_affected_tests(
    changed_files: Iterable[str],
    *,
    explicit_map: dict[str, tuple[str, ...]] | None = None,
) -> TestSelection:
    """Select a conservative targeted test set from changed source paths.

    This function selects affected tests using an explicit mapping (preferred
    for production) or a convention-based fallback. The convention maps
    `src/pkg/mod.py` to `tests/pkg/test_mod.py`. If no target can be inferred,
    the caller is instructed to run the full suite for safety.

    Args:
        changed_files: Iterable of changed file paths.
        explicit_map: Optional explicit mapping from source paths to test paths.

    Returns:
        TestSelection with changed files, selected tests, fallback flag, and reasoning.

    Selection Logic:
        - Use explicit_map if provided (preferred production hook).
        - Convention-based fallback: src/pkg/mod.py -> tests/pkg/test_mod.py.
        - Return selected tests if any were inferred.
        - Return fallback_to_full_suite=True if no tests could be inferred.

    Convention Rules:
        - Source paths must start with "src" or "lib".
        - Source must have .py extension.
        - Test path is tests/<package>/test_<module>.py.

    Side Effects:
        - None (pure selection logic).

    Audit Notes:
        - Explicit mapping is preferred for production accuracy.
        - Convention-based fallback may miss tests for non-standard layouts.
        - Fallback to full suite ensures safety when mapping is incomplete.
        - Recovery: Provide explicit_map for non-standard project layouts.
        - Evidence: Selection includes reasoning for audit traceability.

    Engineering Notes:
        - Trade-off: Convention-based fallback is flexible but may not match all layouts.
        - Design: Conservative approach defaults to full suite when uncertain.
        - Performance: Simple path manipulation is fast and deterministic.
    """
    files = tuple(sorted(set(str(path) for path in changed_files)))
    explicit_map = explicit_map or {}
    selected: set[str] = set()

    for path in files:
        selected.update(explicit_map.get(path, ()))
        posix = PurePosixPath(path.replace("\\", "/"))
        parts = posix.parts
        if len(parts) >= 2 and parts[0] in {"src", "lib"} and posix.suffix == ".py":
            relative = PurePosixPath(*parts[1:])
            selected.add(str(PurePosixPath("tests", *relative.parent.parts, f"test_{relative.name}")))

    if selected:
        return TestSelection(
            changed_files=files,
            selected_tests=tuple(sorted(selected)),
            fallback_to_full_suite=False,
            reason="targeted tests selected from explicit mapping or source convention",
        )

    return TestSelection(
        changed_files=files,
        selected_tests=(),
        fallback_to_full_suite=True,
        reason="no trustworthy affected-test mapping available",
    )

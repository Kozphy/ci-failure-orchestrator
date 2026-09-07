from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable


@dataclass(frozen=True)
class TestSelection:
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

    `explicit_map` is the preferred production hook. A small convention-based
    fallback maps `src/pkg/mod.py` to `tests/pkg/test_mod.py`. If no target can be
    inferred the caller is instructed to run the full suite.
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

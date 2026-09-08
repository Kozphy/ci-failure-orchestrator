"""Affected-test selection using explicit path dependency rules."""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Iterable


@dataclass(frozen=True)
class TestRule:
    __test__ = False
    source_glob: str
    tests: tuple[str, ...]


class AffectedTestSelector:
    def __init__(self, rules: Iterable[TestRule], *, fallback: tuple[str, ...] = ("tests",)):
        self.rules = tuple(rules)
        self.fallback = fallback

    def select(self, changed_files: Iterable[str]) -> tuple[str, ...]:
        selected: set[str] = set()
        for path in changed_files:
            for rule in self.rules:
                if fnmatch(path, rule.source_glob):
                    selected.update(rule.tests)
        return tuple(sorted(selected)) if selected else self.fallback

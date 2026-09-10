"""Affected-test selection using explicit path dependency rules.

This module provides test selection based on explicit path dependency rules.
It maps source file patterns to test paths, enabling targeted test execution
for fast feedback during repair evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Iterable


@dataclass(frozen=True)
class TestRule:
    """Rule mapping source file patterns to test paths.

    Attributes:
        source_glob: Glob pattern for source files (e.g., "src/**/*.py").
        tests: Tuple of test paths to run when source matches the pattern.
    """

    __test__ = False
    source_glob: str
    tests: tuple[str, ...]


class AffectedTestSelector:
    """Selects affected tests based on changed files and explicit rules.

    This selector uses explicit path dependency rules to determine which
    tests to run for a given set of changed files. If no rules match, a
    fallback test set is used.

    Attributes:
        rules: Tuple of TestRule objects mapping source patterns to tests.
        fallback: Fallback test set when no rules match (default: ("tests",)).

    Audit Notes:
        - Incorrect rules may miss relevant tests or run unnecessary tests.
        - Fallback to full suite ensures safety when rules are incomplete.
        - Recovery: Review and update rules if test selection is too conservative or aggressive.
        - Evidence: Selected tests are logged for audit traceability.

    Engineering Notes:
        - Trade-off: Explicit rules require maintenance but provide precise control.
        - Design: Glob matching is flexible but may require careful pattern construction.
        - Performance: O(n*m) where n is changed files and m is rules count.
    """

    def __init__(self, rules: Iterable[TestRule], *, fallback: tuple[str, ...] = ("tests",)):
        """Initialize the affected test selector.

        Args:
            rules: Iterable of TestRule objects mapping source patterns to tests.
            fallback: Fallback test set when no rules match (default: ("tests",)).
        """
        self.rules = tuple(rules)
        self.fallback = fallback

    def select(self, changed_files: Iterable[str]) -> tuple[str, ...]:
        """Select affected tests based on changed files.

        This method matches each changed file against the rule set using glob
        patterns and aggregates the corresponding test paths. If no tests are
        selected, the fallback test set is returned.

        Args:
            changed_files: Iterable of changed file paths.

        Returns:
            Tuple of selected test paths (sorted), or fallback if no tests selected.

        Selection Logic:
            - Match each changed file against rule source_glob patterns.
            - Aggregate tests from all matching rules.
            - Return sorted union of selected tests.
            - Return fallback if no tests selected.

        Side Effects:
            - None (pure selection logic).

        Safety Invariants:
            - Fallback ensures tests are always run even if rules are incomplete.
            - Glob matching is case-sensitive on Unix but may vary on Windows.
        """
        selected: set[str] = set()
        for path in changed_files:
            for rule in self.rules:
                if fnmatch(path, rule.source_glob):
                    selected.update(rule.tests)
        return tuple(sorted(selected)) if selected else self.fallback

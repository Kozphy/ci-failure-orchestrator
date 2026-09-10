"""Git patch validation for bounded, inspectable repair changes.

This module provides validation that repair proposals are represented by bounded,
inspectable git diffs with limits on changed files and diff size to prevent
excessive or unreviewable changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class PatchValidation:
    """Validation result for a git patch.

    Attributes:
        valid: Whether the patch passes validation constraints.
        changed_files: Tuple of file paths changed by the patch.
        diff_stat: Git diff --stat output for the patch.
        reason: Human-readable explanation of the validation result.
    """

    valid: bool
    changed_files: tuple[str, ...]
    diff_stat: str
    reason: str


class GitPatchValidator:
    """Validates that a repair is represented by a bounded, inspectable git diff.

    This validator enforces constraints on repair proposals to ensure they are
    bounded in scope and inspectable for review. It limits the number of changed
    files and the total diff size to prevent excessive or unreviewable changes.

    Attributes:
        max_changed_files: Maximum number of files that can be changed (default: 20).
        max_diff_lines: Maximum number of lines in the git diff (default: 800).

    Audit Notes:
        - Bypassing file or diff limits could allow unreviewable or dangerous changes.
        - Missing git diff indicates the repair produced no changes.
        - Recovery: Review validation limits and adjust if repairs are too restrictive.
        - Evidence: All validation results include changed files, diff stat, and reasoning for audit.

    Engineering Notes:
        - Trade-off: Strict limits ensure reviewability but may reject valid multi-file repairs.
        - Design: File and diff limits enforce bounded scope for repair proposals.
        - Performance: Git diff operations are fast and provide accurate change detection.
    """

    def __init__(self, max_changed_files: int = 20, max_diff_lines: int = 800):
        """Initialize the git patch validator.

        Args:
            max_changed_files: Maximum number of files that can be changed (default: 20).
            max_diff_lines: Maximum number of lines in the git diff (default: 800).
        """
        self.max_changed_files = max_changed_files
        self.max_diff_lines = max_diff_lines

    def validate(self, repo: str | Path) -> PatchValidation:
        """Validate that the git diff in the repository meets validation constraints.

        This method checks the git diff in the repository for changed files and
        diff size, ensuring they are within the configured limits.

        Args:
            repo: Path to the repository to validate.

        Returns:
            PatchValidation with validation result, changed files, diff stat, and reasoning.

        Validation Constraints:
            - Must have at least one changed file.
            - Number of changed files must not exceed max_changed_files.
            - Number of diff lines must not exceed max_diff_lines.

        Side Effects:
            - Executes git commands in the repository.

        Failure Modes:
            - Git commands may fail if repository is not a git repository.
            - Git diff may be empty if no changes were made.
        """
        root = Path(repo)
        changed = self._run(root, ["git", "diff", "--name-only"]).stdout.splitlines()
        diff = self._run(root, ["git", "diff", "--no-ext-diff", "--unified=0"]).stdout
        diff_stat = self._run(root, ["git", "diff", "--stat"]).stdout.strip()

        files = tuple(sorted(f for f in changed if f.strip()))
        if not files:
            return PatchValidation(False, files, diff_stat, "repair produced no git diff")
        if len(files) > self.max_changed_files:
            return PatchValidation(False, files, diff_stat, "changed-file budget exceeded")
        if len(diff.splitlines()) > self.max_diff_lines:
            return PatchValidation(False, files, diff_stat, "diff-size budget exceeded")
        return PatchValidation(True, files, diff_stat, "bounded git diff")

    @staticmethod
    def _run(root: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
        """Run a git command in the repository.

        Args:
            root: Path to the repository root.
            command: Git command to execute as a list of strings.

        Returns:
            CompletedProcess with stdout, stderr, and return code.

        Raises:
            subprocess.CalledProcessError: If the git command fails.
        """
        return subprocess.run(
            command,
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

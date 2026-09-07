from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class PatchValidation:
    valid: bool
    changed_files: tuple[str, ...]
    diff_stat: str
    reason: str


class GitPatchValidator:
    """Validates that a repair is represented by a bounded, inspectable git diff."""

    def __init__(self, max_changed_files: int = 20, max_diff_lines: int = 800):
        self.max_changed_files = max_changed_files
        self.max_diff_lines = max_diff_lines

    def validate(self, repo: str | Path) -> PatchValidation:
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
        return subprocess.run(
            command,
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

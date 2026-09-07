from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Callable


@dataclass(frozen=True)
class RepairPlan:
    strategy: str
    target_path: str
    description: str


@dataclass(frozen=True)
class RepairAttempt:
    strategy: str
    success: bool
    duration_seconds: float
    regression_detected: bool
    stdout: str
    stderr: str

    def to_dict(self) -> dict:
        return asdict(self)


SAFE_STRATEGIES = {
    "replace_text",
    "append_line",
    "remove_line",
}


class RepairPlanner:
    """Deterministic repair planner for benchmark fixtures.

    This intentionally avoids arbitrary shell/code generation. Plans are
    generated from fixture metadata so benchmark results are reproducible.
    """

    def plan(self, case: dict) -> list[RepairPlan]:
        plans = []
        for candidate in case.get("repair_candidates", []):
            strategy = candidate.get("strategy", "")
            if strategy not in SAFE_STRATEGIES:
                continue
            plans.append(
                RepairPlan(
                    strategy=strategy,
                    target_path=candidate["target_path"],
                    description=candidate.get("description", strategy),
                )
            )
        return plans


class SandboxRepairExecutor:
    """Runs deterministic file repairs inside a disposable directory."""

    def __init__(self, verify: Callable[[Path], tuple[bool, bool, str, str]]):
        self.verify = verify

    def run(self, fixture_dir: Path, case: dict, plan: RepairPlan) -> RepairAttempt:
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="ci-repair-") as tmp:
            sandbox = Path(tmp) / "repo"
            shutil.copytree(fixture_dir, sandbox)
            target = sandbox / plan.target_path
            candidate = next(
                c for c in case.get("repair_candidates", [])
                if c.get("strategy") == plan.strategy and c.get("target_path") == plan.target_path
            )
            self._apply(target, candidate)
            success, regression, stdout, stderr = self.verify(sandbox)
        duration = time.perf_counter() - started
        return RepairAttempt(
            strategy=plan.strategy,
            success=success,
            duration_seconds=round(duration, 6),
            regression_detected=regression,
            stdout=stdout,
            stderr=stderr,
        )

    def _apply(self, target: Path, candidate: dict) -> None:
        if not target.exists():
            raise FileNotFoundError(target)
        text = target.read_text(encoding="utf-8")
        strategy = candidate["strategy"]
        if strategy == "replace_text":
            old = candidate["old"]
            new = candidate["new"]
            if old not in text:
                raise ValueError(f"repair token not found in {target}")
            target.write_text(text.replace(old, new, 1), encoding="utf-8")
        elif strategy == "append_line":
            target.write_text(text + candidate["line"] + "\n", encoding="utf-8")
        elif strategy == "remove_line":
            needle = candidate["line"]
            lines = [line for line in text.splitlines() if line != needle]
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            raise ValueError(f"unsafe repair strategy: {strategy}")


def pytest_verifier(command: tuple[str, ...] = ("python", "-m", "pytest", "-q")):
    def verify(repo: Path) -> tuple[bool, bool, str, str]:
        completed = subprocess.run(
            command,
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        passed = completed.returncode == 0
        return passed, not passed, completed.stdout, completed.stderr

    return verify

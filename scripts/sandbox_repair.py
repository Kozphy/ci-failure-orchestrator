from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

DENY_PREFIXES = (".github/", ".git/", "secrets/", ".env")
MAX_CHANGED_FILES = 5
MAX_DIFF_LINES = 500


@dataclass(frozen=True)
class RepairEvidence:
    accepted: bool
    reason: str
    changed_files: tuple[str, ...]
    diff_lines: int
    targeted_passed: bool
    regression_passed: bool


def changed_files(repo: Path) -> tuple[str, ...]:
    out = subprocess.check_output(
        ["git", "diff", "--name-only"], cwd=repo, text=True
    )
    return tuple(line.strip() for line in out.splitlines() if line.strip())


def diff_line_count(repo: Path) -> int:
    out = subprocess.check_output(["git", "diff", "--unified=0"], cwd=repo, text=True)
    return len(out.splitlines())


def validate_scope(files: tuple[str, ...], diff_lines: int) -> tuple[bool, str]:
    if not files:
        return False, "agent produced no changes"
    if len(files) > MAX_CHANGED_FILES:
        return False, f"repair changes {len(files)} files; limit is {MAX_CHANGED_FILES}"
    if diff_lines > MAX_DIFF_LINES:
        return False, f"repair diff has {diff_lines} lines; limit is {MAX_DIFF_LINES}"
    denied = [path for path in files if path.startswith(DENY_PREFIXES)]
    if denied:
        return False, f"repair touched protected paths: {', '.join(denied)}"
    return True, "repair is within bounded scope"


def run_command(command: str, *, cwd: Path) -> bool:
    result = subprocess.run(shlex.split(command), cwd=cwd, check=False)
    return result.returncode == 0


def evaluate(repo: Path, targeted: str, regression: str) -> RepairEvidence:
    files = changed_files(repo)
    lines = diff_line_count(repo)
    accepted, reason = validate_scope(files, lines)
    if not accepted:
        return RepairEvidence(False, reason, files, lines, False, False)

    targeted_passed = run_command(targeted, cwd=repo)
    if not targeted_passed:
        return RepairEvidence(False, "targeted verification failed", files, lines, False, False)

    regression_passed = run_command(regression, cwd=repo)
    if not regression_passed:
        return RepairEvidence(False, "regression verification failed", files, lines, True, False)

    return RepairEvidence(True, "repair passed independent evaluation", files, lines, True, True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a bounded CI repair in an isolated worktree")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--logs", required=True)
    parser.add_argument("--agent-cmd", required=True)
    parser.add_argument("--targeted", default="python -m pytest -q")
    parser.add_argument("--regression", default="python -m pytest -q")
    parser.add_argument("--output", default="repair-evidence.json")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    logs = Path(args.logs).resolve()
    if not repo.is_dir() or not logs.is_file():
        raise SystemExit("repair repo or log file does not exist")

    env = os.environ.copy()
    env["CI_REPAIR_LOGS"] = str(logs)
    env["CI_REPAIR_REPO"] = str(repo)
    # Never forward GitHub write credentials into the coding-agent process.
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
        env.pop(key, None)

    result = subprocess.run(
        shlex.split(args.agent_cmd), cwd=repo, env=env, check=False
    )
    if result.returncode != 0:
        evidence = RepairEvidence(False, "coding agent failed", (), 0, False, False)
    else:
        evidence = evaluate(repo, args.targeted, args.regression)

    Path(args.output).write_text(json.dumps(asdict(evidence), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(asdict(evidence)))
    return 0 if evidence.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())

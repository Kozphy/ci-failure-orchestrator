"""``actions-doctor demo``: failure -> diagnosis -> proposal -> verification -> policy -> evidence.

Each scenario builds a throwaway git repository, diagnoses its saved CI log with the same
code as ``analyze``, and hands a recorded patch to ``fix-repo``, which verifies it in a
disposable worktree and lets the policy engine decide. No model, token or network is used,
and nothing outside the work directory is written.
"""

from __future__ import annotations

import difflib
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..ci_audit.collect import failure_event_fields
from ..service.run import FixRepoConfig, run_fix_repo
from .diagnose import Diagnosis, diagnose_log
from .scenarios import Scenario

_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "CI Doctor demo",
    "GIT_AUTHOR_EMAIL": "demo@example.invalid",
    "GIT_COMMITTER_NAME": "CI Doctor demo",
    "GIT_COMMITTER_EMAIL": "demo@example.invalid",
    "GIT_AUTHOR_DATE": "2026-09-30T08:00:00Z",
    "GIT_COMMITTER_DATE": "2026-09-30T08:00:00Z",
}
_LABEL_WIDTH = 15
_NEXT = {
    "APPROVED": (
        "fix-repo-apply would push the verified patch to a new branch and open a draft PR; nothing is merged. "
        "The demo stops here."
    ),
    "AWAITING_HUMAN": (
        "A maintainer reviews the evidence and decides with foundation-decide. Nothing is applied until then."
    ),
}


@dataclass(frozen=True)
class DemoResult:
    """Outcome of one demo scenario run and whether it matched the scenario's expectations."""

    scenario: str
    category: str
    outcome: str
    rules: tuple[str, ...]
    run_id: str
    artifacts: str
    as_expected: bool


def _write(root: Path, files: Mapping[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


def _git(repo: Path, *args: str) -> None:
    env = {**os.environ, **_GIT_IDENTITY}
    subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def build_repository(scenario: Scenario, repo: Path) -> None:
    """The scenario's repository at the failing commit, as a one-commit git history."""
    repo.mkdir(parents=True)
    _write(repo, scenario.files)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"{scenario.title}: the commit CI failed on")


def recorded_patch(scenario: Scenario) -> str:
    """Unified diff from the failing files to the recorded fix."""
    chunks: list[str] = []
    for rel, after in scenario.fix.items():
        before = scenario.files[rel]
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True), f"a/{rel}", f"b/{rel}"
            )
        )
    return "".join(chunks)


def _verify_commands(scenario: Scenario) -> list[str]:
    return [command.format(python=f'"{sys.executable}"') for command in scenario.verify]


def _matches(expected: tuple[str, ...], rules: tuple[str, ...]) -> bool:
    return all(any(rule == e or rule.startswith(f"{e}-") for rule in rules) for e in expected)


def run_scenario(scenario: Scenario, workdir: Path) -> tuple[DemoResult, list[str]]:
    """Run one scenario end to end; returns the result and the report lines."""
    base = workdir / scenario.name
    repo = base / "repo"
    build_repository(scenario, repo)
    log_path = base / "ci-job.log"
    log_path.write_bytes(scenario.ci_log.encode("utf-8"))
    patch_path = base / "recorded-fix.diff"
    patch_path.write_bytes(recorded_patch(scenario).encode("utf-8"))

    diagnosis = diagnose_log(scenario.ci_log, job=scenario.job, step=scenario.step)
    failure = {
        "source": "actions-doctor-demo",
        **failure_event_fields("", {"name": scenario.job, "failed_step": scenario.step}, scenario.ci_log),
    }
    outcome = run_fix_repo(
        FixRepoConfig(
            repo_path=repo,
            verify_commands=_verify_commands(scenario),
            patch_file=patch_path,
            verify_timeout=scenario.verify_timeout,
            artifacts_root=workdir / "artifacts",
            failure=failure,
        )
    )
    top = diagnosis.findings[0]
    rules = tuple(outcome.get("policy_rules") or ())
    result = DemoResult(
        scenario=scenario.name,
        category=top.policy_category,
        outcome=str(outcome.get("outcome")),
        rules=rules,
        run_id=str(outcome.get("run_id") or ""),
        artifacts=str(outcome.get("artifacts") or ""),
        as_expected=(
            top.policy_category == scenario.expected_category
            and outcome.get("outcome") == scenario.expected_outcome
            and _matches(scenario.expected_rules, rules)
        ),
    )
    return result, _report(scenario, diagnosis, outcome, result, log_path, patch_path)


def _row(label: str, text: str) -> list[str]:
    pad = " " * _LABEL_WIDTH
    lines = text.splitlines() or [""]
    return [f"{label.ljust(_LABEL_WIDTH)}{lines[0]}".rstrip()] + [f"{pad}{line}".rstrip() for line in lines[1:]]


_KEY_EVIDENCE = (
    "input/failure-event.json",
    "classification/classification.json",
    "sandbox/sandbox-001.json",
    "policy/policy-decision.json",
    "fix-repo/final.patch",
    "fix-repo/environment-escalation.json",
    "escalation/summary.md",
    "events.jsonl",
)


def _evidence_files(artifacts: str) -> tuple[list[str], int]:
    """The files a reviewer opens first, and how many the run wrote in total."""
    root = Path(artifacts)
    if not root.is_dir():
        return [], 0
    written = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    return [name for name in _KEY_EVIDENCE if name in written], len(written)


def _report(
    scenario: Scenario,
    diagnosis: Diagnosis,
    outcome: dict[str, Any],
    result: DemoResult,
    log_path: Path,
    patch_path: Path,
) -> list[str]:
    top = diagnosis.findings[0]
    shown_verify = ", ".join(command.format(python="python") for command in scenario.verify)
    lines = [f"== {scenario.name}: {scenario.title} ==", *_row("Scenario", scenario.story), ""]
    where = f'job "{top.job}" > step "{top.step}"'
    if top.evidence_line is not None:
        where += f" > log line {top.evidence_line}"
    lines += _row("1 Failure", f"{where}\n{top.message}")
    lines += _row("", f"saved log: {log_path}")
    lines += _row(
        "2 Diagnosis",
        f"{top.category} (confidence {top.confidence}; the policy engine sees {top.policy_category})\n"
        f"{diagnosis.next_step}",
    )
    escalation = outcome.get("escalation")
    if escalation:
        finding = escalation["finding"]
        lines += _row("3 Proposal", "not requested: no model or patch is consulted for an environment failure")
        lines += _row(
            "4 Verification",
            f"reproduced locally with: {shown_verify}\n"
            f"the reproduction failed for an environment reason ({finding['kind']}): {finding['evidence']}",
        )
        lines += _row("5 Policy", f"{outcome['outcome']}: {escalation['reason']}; escalated before any patch exists")
    else:
        files = ", ".join(outcome.get("files_changed") or ()) or "(patch rejected before verification)"
        lines += _row("3 Proposal", f"recorded patch, no model called: {files}\n{patch_path}")
        lines += _row(
            "4 Verification",
            f"failed at the base commit, then {outcome.get('technical_status')} with the patch, in a disposable "
            f"worktree:\n{shown_verify}",
        )
        rules = "\n".join(result.rules) or "(none)"
        lines += _row("5 Policy", f"{outcome.get('policy_outcome')} -> {outcome['outcome']}\n{rules}")
    key_files, total = _evidence_files(result.artifacts)
    lines += _row("6 Evidence", f"{result.artifacts} ({total} files), including:")
    lines += [f"{' ' * _LABEL_WIDTH}  {name}" for name in key_files]
    lines += _row("Next", _NEXT.get(result.outcome, "inspect the evidence directory"))
    expected = f"{scenario.expected_category}, {scenario.expected_outcome}"
    if scenario.expected_rules:
        expected += ", " + " ".join(scenario.expected_rules)
    lines += _row("Expected", f"{expected}: {'matched' if result.as_expected else 'NOT MATCHED'}")
    return lines + [""]

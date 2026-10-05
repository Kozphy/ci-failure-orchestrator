"""Reproducible broken-CI demo: failing CI -> diagnosis -> verified repair -> green tests -> evidence.

Run from the repository root (the package must be importable, e.g. ``pip install -e .``)::

    python examples/demo-repo/run_demo.py [--workdir DIR]

The script copies ``project/`` into a fresh git repository and then runs only the public
commands a customer would run. Every step's output stays in the work directory; nothing is
pushed, no token or model is used, and nothing is merged.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE.parents[1]
CI_COMMAND = (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider")
VERIFY_COMMAND = "python -m pytest -q -p no:cacheprovider tests/test_versions.py"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Release Bot",
    "GIT_AUTHOR_EMAIL": "release-bot@example.invalid",
    "GIT_COMMITTER_NAME": "Release Bot",
    "GIT_COMMITTER_EMAIL": "release-bot@example.invalid",
    "GIT_AUTHOR_DATE": "2026-10-01T09:00:00Z",
    "GIT_COMMITTER_DATE": "2026-10-01T09:00:00Z",
}


class DemoError(RuntimeError):
    """A demo step did not behave as the scenario requires."""


def _env() -> dict[str, str]:
    """Environment for every child process: git identity, this Python first on PATH, the package importable."""
    env = {**os.environ, **GIT_IDENTITY}
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(SOURCE_ROOT), env.get("PYTHONPATH", "")) if p)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(argv: list[str] | tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), cwd=cwd, env=_env(), capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )


def _git(repo: Path, *args: str) -> str:
    result = _run(["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args], repo)
    if result.returncode != 0:
        raise DemoError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _orchestrator(*args: str | Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "-m", "ci_failure_orchestrator.cli", *map(str, args)], cwd)


def _step(number: int, title: str, *lines: str) -> None:
    print(f"\n[{number}] {title}")
    for line in lines:
        print(f"    {line}")


def _actions_log(output: str, returncode: int) -> str:
    """Wrap real command output in the step envelope GitHub Actions adds to a downloaded job log."""
    stamp = "2026-10-01T09:00:00.0000000Z "
    shown = " ".join(["python", *CI_COMMAND[1:]])
    lines = [f"##[group]Run {shown}", shown, "shell: /usr/bin/bash -e {0}", "##[endgroup]", *output.splitlines()]
    lines.append(f"##[error]Process completed with exit code {returncode}.")
    return "".join(f"{stamp}{line}\n" for line in lines)


def _copy_lf(source: Path, target: Path) -> None:
    """Copy text files with LF endings so the recorded patch applies even after a CRLF checkout."""
    for path in source.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            out = target / path.relative_to(source)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def _json_output(result: subprocess.CompletedProcess[str], what: str) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DemoError(f"{what} did not print JSON (exit {result.returncode}): {result.stderr.strip()[-500:]}") from exc


def run_demo(workdir: Path) -> dict:
    """Run the scenario in ``workdir`` and return a summary of what each step produced.

    Args:
        workdir: Empty or missing directory for the repository, logs and evidence.

    Returns:
        Summary with the run id, remediation state, evidence report paths and both CI exit codes.

    Raises:
        DemoError: When a step does not behave as the scenario requires.
    """
    if workdir.exists() and any(workdir.iterdir()):
        raise DemoError(f"work directory must be empty or not exist yet: {workdir}")
    workdir.mkdir(parents=True, exist_ok=True)
    repo = workdir / "repo"
    artifacts = workdir / "artifacts"
    _copy_lf(HERE / "project", repo)
    patch = workdir / "teammate-fix.diff"
    patch.write_bytes((HERE / "fix.diff").read_bytes().replace(b"\r\n", b"\n"))
    _git(repo, "init", "-q")
    _git(repo, "checkout", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Compare release versions in is_newer")
    print(f"CI Doctor end-to-end demo | work directory: {workdir}")

    ci_before = _run(CI_COMMAND, repo)
    log_path = workdir / "ci-failure.log"
    log_path.write_text(_actions_log(ci_before.stdout + ci_before.stderr, ci_before.returncode), encoding="utf-8")
    if ci_before.returncode == 0:
        raise DemoError("the demo repository's tests passed; expected the CI command to fail")
    failed = [line for line in ci_before.stdout.splitlines() if line.startswith("FAILED ")]
    _step(1, "CI fails", f"$ {' '.join(['python', *CI_COMMAND[1:]])}  -> exit {ci_before.returncode}", *failed,
          f"log: {log_path}")

    diagnosed = _run(
        [sys.executable, "-m", "ci_failure_orchestrator.doctor.cli", "diagnose", "--log", str(log_path),
         "--job", "test", "--step", "Run tests", "--json", "--out", str(workdir)],
        workdir,
    )
    diagnosis = _json_output(diagnosed, "actions-doctor diagnose")
    top = diagnosis["findings"][0]
    _step(2, "Diagnosis (read-only)", f"class: {top['category']} (confidence {top['confidence']})",
          f"evidence: {top['message']}", f"next step: {diagnosis['next_step']}",
          f"file: {workdir / 'diagnosis.json'}")

    fixed = _orchestrator(
        "fix-repo", "--repo-path", repo, "--verify", VERIFY_COMMAND, "--patch-file", patch,
        "--log-file", log_path, "--verification-config", HERE / "verify.yml", "--artifacts", artifacts,
        cwd=workdir,
    )
    outcome = _json_output(fixed, "ci-orchestrator fix-repo")
    run_id = str(outcome.get("run_id") or "")
    if outcome.get("outcome") != "APPROVED" or not run_id:
        raise DemoError(f"fix-repo did not approve the patch: {json.dumps(outcome)[:800]}")
    _step(3, "Proposed repair verified in a disposable worktree",
          f"patch: {patch} (a teammate's fix; no model is called)",
          f"policy: {outcome.get('policy_outcome')} -> {outcome['outcome']} | run {run_id}",
          f"remediation state: {outcome.get('remediation_state')}")

    applied = _orchestrator("fix-repo-apply", run_id, "--artifacts", artifacts, "--actor", "demo-operator", cwd=workdir)
    apply_result = _json_output(applied, "ci-orchestrator fix-repo-apply")
    branch = str(apply_result.get("branch") or "")
    if applied.returncode != 0 or not branch:
        raise DemoError(f"fix-repo-apply did not create a branch: {json.dumps(apply_result)[:800]}")
    _step(4, "Applied to a new local branch (not pushed, not merged)", f"branch: {branch}",
          f"commit: {apply_result.get('commit')}", f"main is untouched: {_git(repo, 'rev-parse', '--short', 'main')}")

    _git(repo, "checkout", "-q", branch)
    ci_after = _run(CI_COMMAND, repo)
    (workdir / "ci-after-fix.log").write_text(ci_after.stdout + ci_after.stderr, encoding="utf-8")
    if ci_after.returncode != 0:
        raise DemoError("the CI command still fails on the fix branch")
    summary_line = (ci_after.stdout.strip().splitlines() or [""])[-1]
    _step(5, "CI command is green on the fix branch", f"exit 0: {summary_line}")

    reported = _orchestrator("fix-repo-report", run_id, "--artifacts", artifacts, "--format", "json", cwd=workdir)
    report = _json_output(reported, "ci-orchestrator fix-repo-report")
    fix_dir = artifacts / "runs" / run_id / "fix-repo"
    _step(6, "Evidence report", f"{fix_dir / 'evidence-report.md'}", f"{fix_dir / 'evidence-report.json'}",
          f"state: {report['outcome']['remediation_state']} | verified: {report['outcome']['verified']}",
          "Real CI has not run, so the repair is not VERIFIED_FIXED yet. After pushing the branch,",
          f"`ci-orchestrator fix-repo-verify-ci {run_id} --repository <owner/name>` reads the GitHub run",
          "for that commit and records VERIFIED_FIXED or CI_GREEN_BUT_UNVERIFIED.")
    return {
        "run_id": run_id,
        "branch": branch,
        "remediation_state": report["outcome"]["remediation_state"],
        "ci_before_exit": ci_before.returncode,
        "ci_after_exit": ci_after.returncode,
        "evidence_markdown": str(fix_dir / "evidence-report.md"),
        "evidence_json": str(fix_dir / "evidence-report.json"),
    }


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv``, run the demo and return 0 on success or 1 when a step misbehaves."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workdir", help="Empty directory for the demo (default: a new temp directory)")
    args = parser.parse_args(argv)
    workdir = Path(args.workdir).resolve() if args.workdir else Path(tempfile.mkdtemp(prefix="ci-doctor-e2e-"))
    try:
        run_demo(workdir)
    except DemoError as exc:
        print(f"\ndemo failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

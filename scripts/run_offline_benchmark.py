"""Run surviving offline control-plane checks and write one evidence envelope.

After the control-plane cut, agent-repair and research scripts are gone. This
runner executes the foundation golden benchmark only. A non-zero exit or missing
output makes the envelope ``FAILED``. Missing evidence is never reported as success.

No live model credential is read or required. ``GITHUB_TOKEN`` and ``GH_TOKEN``
are removed from the child environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORPORA = (
    "benchmark/ci_failure_corpus.v1.json",
    "benchmark/repair_fixture_corpus.v1.json",
)


def file_sha256(path: Path) -> str:
    """SHA-256 of the file bytes as written."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_text_sha256(path: Path) -> str:
    """SHA-256 of the file with CRLF normalized to LF."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def git_head(root: Path) -> str:
    """Current commit, or ``unknown`` when git is unavailable."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def child_env(root: Path) -> dict[str, str]:
    """Environment for child benchmarks: repo root importable, no GitHub token."""
    env = os.environ.copy()
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(root) if not previous else str(root) + os.pathsep + previous
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("GITHUB_TOKEN", None)
    env.pop("GH_TOKEN", None)
    return env


def run_step(root: Path, name: str, args: list[str], output: Path) -> dict[str, Any]:
    """Run one command. The output path is recorded even when the command fails."""
    proc = subprocess.run(
        args, cwd=root, env=child_env(root), capture_output=True, text=True, check=False
    )
    present = output.is_file() and output.stat().st_size > 0
    try:
        reported = output.relative_to(root).as_posix()
    except ValueError:
        reported = output.as_posix()
    return {
        "name": name,
        "argv": args[1:],
        "exit_code": proc.returncode,
        "output": reported,
        "output_present": present,
        "output_sha256": file_sha256(output) if present else None,
        "stderr_tail": proc.stderr[-400:],
    }


def judge(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Fail closed when any step failed or left no output."""
    failed = [step["name"] for step in steps if step["exit_code"] != 0 or not step["output_present"]]
    return {"status": "FAILED" if failed else "PASSED", "failed_steps": failed}


def measurements(output_dir: Path) -> dict[str, Any]:
    """Headline fields from the foundation benchmark report when present."""
    report = output_dir / "foundation-benchmark.json"
    payload = None
    if report.is_file() and report.stat().st_size > 0:
        loaded = json.loads(report.read_text(encoding="utf-8"))
        payload = loaded if isinstance(loaded, dict) else None
    return {
        "evidence_class": "synthetic_fixture",
        "independently_labelled_cases": 0,
        "foundation_benchmark": None
        if payload is None
        else {
            "passed": payload.get("passed"),
            "failed": payload.get("failed"),
            "exit_code": payload.get("exit_code"),
        },
    }


def render_markdown(evidence: dict[str, Any]) -> str:
    """Short human-readable summary. Synthetic results stay labelled as synthetic."""
    lines = [
        "# Offline benchmark evidence",
        "",
        f"Status: **{evidence['status']}**",
        "",
        "These numbers come from author-written synthetic fixtures. They are not production",
        "validation and they include no independently labelled external case.",
        "",
        f"- Git commit: `{evidence['git_commit']}`",
        f"- Python: `{evidence['python']}`",
        f"- Platform: `{evidence['platform']}`",
        "",
        "| Step | Exit | Output present |",
        "| --- | --- | --- |",
    ]
    for step in evidence["steps"]:
        lines.append(f"| {step['name']} | {step['exit_code']} | {step['output_present']} |")
    if evidence["failed_steps"]:
        lines.extend(["", "Failed steps: " + ", ".join(evidence["failed_steps"])])
    lines.extend(
        [
            "",
            "Headline measurements (null when that step did not produce a file):",
            "",
            "```json",
            json.dumps(evidence["measurements"], indent=2, sort_keys=True),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def build_evidence(root: Path, output_dir: Path) -> dict[str, Any]:
    """Run the foundation golden benchmark and return the envelope."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "foundation-benchmark.json"
    # Capture CLI JSON by redirecting stdout into the report file via a wrapper.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ci_failure_orchestrator.cli",
            "foundation-benchmark",
            "--cases",
            "benchmarks/foundation/cases",
            "--baseline",
            "benchmarks/foundation/baselines/current.json",
            "--artifacts",
            str(output_dir / "foundation-artifacts"),
        ],
        cwd=root,
        env=child_env(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.stdout.strip():
        report_path.write_text(proc.stdout, encoding="utf-8")
    try:
        reported = report_path.relative_to(root).as_posix()
    except ValueError:
        reported = report_path.as_posix()
    present = report_path.is_file() and report_path.stat().st_size > 0
    step = {
        "name": "foundation_benchmark",
        "argv": ["-m", "ci_failure_orchestrator.cli", "foundation-benchmark"],
        "exit_code": proc.returncode,
        "output": reported,
        "output_present": present,
        "output_sha256": file_sha256(report_path) if present else None,
        "stderr_tail": proc.stderr[-400:],
    }
    verdict = judge([step])
    return {
        "schema_version": "1.0",
        "benchmark": "offline-envelope",
        "status": verdict["status"],
        "failed_steps": verdict["failed_steps"],
        "git_commit": git_head(root),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "credentials": "none",
        "corpora": [{"path": rel, "sha256": canonical_text_sha256(root / rel)} for rel in CORPORA],
        "steps": [step],
        "measurements": measurements(output_dir),
        "scope": "synthetic fixtures only; external cases in benchmark/external_cases.v0.json are unlabelled",
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Writes evidence.json and evidence.md. Exit 1 when the envelope failed."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "benchmarks" / "offline")
    args = parser.parse_args(argv)
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    evidence = build_evidence(ROOT, output_dir)
    (output_dir / "evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "evidence.md").write_text(render_markdown(evidence), encoding="utf-8")
    print(json.dumps({"status": evidence["status"], "output_dir": str(output_dir)}, sort_keys=True))
    return 0 if evidence["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the existing offline benchmarks and write one evidence envelope.

This does not score cases itself. It calls the current corpus, baseline, RQ1 and repair-fixture
scripts. A step that exits non-zero, or that does not leave a non-empty output file, makes the
envelope status ``FAILED``. Missing evidence is never reported as success.

No live model credential is read or required. ``GITHUB_TOKEN`` and ``GH_TOKEN`` are removed from
the child environment.
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
    """SHA-256 of the file bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    """Run one existing script. The output path is recorded even when the script fails."""
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


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def measurements(output_dir: Path) -> dict[str, Any]:
    """Copy headline fields from child outputs. Absent files stay null."""
    matrix = _read_json(output_dir / "baseline-matrix.json")
    rq1 = _read_json(output_dir / "rq1.json")
    corpus = _read_json(output_dir / "corpus-benchmark.json")
    repair = _read_json(output_dir / "repair-fixture-benchmark.json")
    return {
        "evidence_class": "synthetic_fixture",
        "independently_labelled_cases": 0,
        "baseline_matrix": None
        if matrix is None
        else [
            {"baseline_id": row.get("baseline_id"), "cases": row.get("cases"), "top1_accuracy": row.get("top1_accuracy")}
            for row in matrix.get("systems", [])
        ],
        "rq1_metrics": None if rq1 is None else rq1.get("metrics"),
        "corpus_metrics": None if corpus is None else corpus.get("metrics"),
        "repair_fixture_metrics": None if repair is None else repair.get("metrics"),
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
    lines.extend(["", "Headline measurements (null when that step did not produce a file):", "", "```json",
                  json.dumps(evidence["measurements"], indent=2, sort_keys=True), "```", ""])
    return "\n".join(lines)


def build_evidence(root: Path, output_dir: Path) -> dict[str, Any]:
    """Run the four existing benchmarks and return the envelope."""
    output_dir.mkdir(parents=True, exist_ok=True)
    commands = [
        ("baseline_matrix", [sys.executable, "scripts/run_baseline_matrix.py", "--output",
                             str(output_dir / "baseline-matrix.json")], output_dir / "baseline-matrix.json"),
        ("rq1", [sys.executable, "scripts/run_research_rq1.py", "--output", str(output_dir / "rq1.json")],
         output_dir / "rq1.json"),
        ("corpus", [sys.executable, "scripts/run_corpus_benchmark.py", "benchmark/ci_failure_corpus.v1.json",
                    "--output", str(output_dir / "corpus-benchmark.json")], output_dir / "corpus-benchmark.json"),
        ("repair_fixture", [sys.executable, "scripts/run_repair_fixture_benchmark.py",
                            "benchmark/repair_fixture_corpus.v1.json", "--output",
                            str(output_dir / "repair-fixture-benchmark.json")],
         output_dir / "repair-fixture-benchmark.json"),
    ]
    steps = [run_step(root, name, args, output) for name, args, output in commands]
    verdict = judge(steps)
    return {
        "schema_version": "1.0",
        "benchmark": "offline-envelope",
        "status": verdict["status"],
        "failed_steps": verdict["failed_steps"],
        "git_commit": git_head(root),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "credentials": "none",
        "corpora": [
            {"path": rel, "sha256": file_sha256(root / rel)} for rel in CORPORA
        ],
        "steps": steps,
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

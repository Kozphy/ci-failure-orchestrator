"""Record bounded checks, command output, source hashes and actual exit codes.

Run from a source checkout. A nonzero exit includes failed or unavailable tools;
read each record rather than interpreting this script as a certification gate.
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def collect(label):
    out = ROOT / "evidence" / "edas-v2" / label
    out.mkdir(parents=True, exist_ok=False)
    commands = [
        ("canonical-adversarial", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p",
                                   "test_assurance_regressions.py", "-v"], 60),
        ("full-pytest", [sys.executable, "-m", "pytest", "--cov=ci_failure_orchestrator",
                         "--cov-report=term-missing"], 300),
        ("ruff", [sys.executable, "-m", "ruff", "check", "examples/edas", "tests/test_edas_reference.py",
                  "tests/test_assurance_regressions.py", "scripts/collect_engineering_evidence.py"], 60),
        ("mypy-availability", [sys.executable, "-m", "mypy", "--version"], 30),
        ("foundation-benchmark", [sys.executable, "-m", "ci_failure_orchestrator.cli",
                                  "foundation-benchmark", "--compare-baseline"], 180),
    ]
    if (ROOT / "examples" / "edas" / "core.py").is_file():
        commands.extend([
            ("edas-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p",
                            "test_edas_reference.py", "-v"], 60),
            ("edas-evaluation", [sys.executable, "-m", "examples.edas.evaluate"], 60),
        ])
    records = []
    for name, command, timeout in commands:
        started = time.perf_counter()
        try:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as exc:
            code, stdout, stderr = None, str(exc.stdout or ""), "check timed out"
        duration = time.perf_counter() - started
        output = out / (name + ".txt")
        output.write_text(stdout + "\nSTDERR:\n" + stderr, encoding="utf-8")
        records.append(dict(name=name, command=command, timeout_seconds=timeout,
                            exit_code=code, elapsed_seconds=duration, output=str(output.relative_to(ROOT)),
                            output_sha256=hashlib.sha256(output.read_bytes()).hexdigest()))
        print(name, "exit=", code, "seconds=", round(duration, 3), flush=True)
    sources = {}
    for directory in ("ci_failure_orchestrator", "examples/edas", "tests"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = dict(schema_version="edas-evidence.v1", label=label,
                  collected_at=datetime.now(timezone.utc).isoformat(), python=sys.version,
                  platform=platform.platform(), executable=sys.executable,
                  base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  dirty_status=subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
                  sources_sha256=sources, checks=records)
    (out / "checks.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return int(any(r["exit_code"] != 0 for r in records))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, choices=("baseline", "final", "reviewed", "replication"))
    sys.exit(collect(parser.parse_args().label))

"""Claim registry checker: ``python -m research.claims [--require-committed]``.

``research/CLAIMS.md`` holds one markdown table. Each row is a claim with an ID, a status, the
experiment it rests on and machine-checkable assertions against that experiment's ``metrics.json``.
This module parses the table and fails if any row is inconsistent with the committed raw results:

* the status is not one of SUPPORTED, PARTIALLY_SUPPORTED, PENDING, UNSUPPORTED;
* a SUPPORTED or PARTIALLY_SUPPORTED claim has no experiment, no checks, or a failing check;
* a SUPPORTED claim rests on a run whose manifest records ``git_dirty: true`` or a non-test split;
* any cited experiment directory is missing (or, with ``--require-committed``, untracked by git);
* the manuscript cites a claim ID that is not in the registry.

Check syntax: ``path op value`` separated by ``;``. ``path`` is ``/``-separated keys into metrics.json
(keys may contain spaces, e.g. ``comparisons/repair/P vs R-GREEN-k/...``),
``op`` is one of ``== != <= >= < >`` and ``value`` is a JSON literal (``3``, ``0.5``, ``null``).
"""

from __future__ import annotations

import argparse
import json
import operator
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import RAW_DIR, ROOT

CLAIMS_PATH = ROOT / "research" / "CLAIMS.md"
MANUSCRIPT_PATH = ROOT / "research" / "paper" / "manuscript.md"
STATUSES = ("SUPPORTED", "PARTIALLY_SUPPORTED", "PENDING", "UNSUPPORTED")
EVIDENCE_REQUIRED = ("SUPPORTED", "PARTIALLY_SUPPORTED")
COLUMNS = ("ID", "Claim", "Status", "Experiment", "Checks", "Scope and caveats")
_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq, "!=": operator.ne, "<=": operator.le, ">=": operator.ge, "<": operator.lt, ">": operator.gt,
}
_CHECK_RE = re.compile(r"^\s*(?P<path>[^<>=!]+?)\s*(?P<op>==|!=|<=|>=|<|>)\s*(?P<value>.+?)\s*$")
_ID_RE = re.compile(r"^C\d+$")
_CITE_RE = re.compile(r"\[(C\d+)\]")
_EMPTY = {"", "-", "n/a"}


@dataclass
class Claim:
    """One row of the claim registry."""

    claim_id: str
    text: str
    status: str
    experiment: str | None
    checks: list[str]
    scope: str
    line: int


@dataclass
class Report:
    """Result of checking the registry."""

    claims: list[Claim] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    checks_passed: int = 0

    @property
    def ok(self) -> bool:
        """Whether no problem was found."""
        return not self.problems


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_claims(text: str) -> tuple[list[Claim], list[str]]:
    """Parse the first table whose header matches ``COLUMNS``; return claims and parse problems."""
    lines = text.splitlines()
    problems: list[str] = []
    start = next((i for i, line in enumerate(lines) if tuple(_cells(line)) == COLUMNS), None)
    if start is None:
        return [], [f"no claim table with header {' | '.join(COLUMNS)}"]
    claims: list[Claim] = []
    for offset, line in enumerate(lines[start + 2:], start=start + 3):
        if not line.strip().startswith("|"):
            break
        cells = _cells(line)
        if len(cells) != len(COLUMNS):
            problems.append(f"line {offset}: expected {len(COLUMNS)} cells, found {len(cells)}")
            continue
        cid, claim_text, status, experiment, checks, scope = cells
        experiment = experiment.strip("`")
        claims.append(Claim(
            claim_id=cid, text=claim_text, status=status.strip("*"),
            experiment=None if experiment in _EMPTY else experiment,
            checks=[] if checks in _EMPTY else [c.strip().strip("`") for c in checks.split(";") if c.strip()],
            scope=scope, line=offset,
        ))
    return claims, problems


def _lookup(data: Any, path: str) -> Any:
    for key in path.split("/"):
        if isinstance(data, Mapping) and key in data:
            data = data[key]
        elif isinstance(data, list) and key.isdigit() and int(key) < len(data):
            data = data[int(key)]
        else:
            raise KeyError(path)
    return data


def evaluate_check(metrics: Mapping[str, Any], check: str) -> tuple[bool, str]:
    """Evaluate one ``path op value`` assertion; return (passed, explanation)."""
    match = _CHECK_RE.match(check)
    if not match:
        return False, f"unparseable check {check!r}"
    try:
        expected = json.loads(match["value"])
    except json.JSONDecodeError:
        return False, f"value in {check!r} is not a JSON literal"
    try:
        actual = _lookup(metrics, match["path"])
    except KeyError:
        return False, f"path {match['path']!r} not found in metrics.json"
    op = match["op"]
    if isinstance(actual, float) and isinstance(expected, (int, float)) and op in ("==", "!="):
        equal = abs(actual - expected) <= 1e-9
        return (equal if op == "==" else not equal), f"{match['path']} = {actual!r}"
    try:
        return bool(_OPS[op](actual, expected)), f"{match['path']} = {actual!r}"
    except TypeError:
        return False, f"cannot compare {actual!r} {op} {expected!r}"


def _tracked(path: Path) -> bool:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path.relative_to(ROOT))],
            cwd=ROOT, capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def check_registry(
    claims_text: str,
    *,
    raw_root: Path = RAW_DIR,
    manuscript_text: str | None = None,
    require_committed: bool = False,
) -> Report:
    """Check every claim against its experiment; see the module docstring for the rules."""
    claims, problems = parse_claims(claims_text)
    report = Report(claims=claims, problems=list(problems))
    seen: set[str] = set()
    cache: dict[str, tuple[dict[str, Any], dict[str, Any]] | None] = {}
    for claim in claims:
        where = f"{claim.claim_id} (line {claim.line})"
        if not _ID_RE.match(claim.claim_id):
            report.problems.append(f"{where}: ID must look like C1, C2, ...")
        if claim.claim_id in seen:
            report.problems.append(f"{where}: duplicate ID")
        seen.add(claim.claim_id)
        if claim.status not in STATUSES:
            report.problems.append(f"{where}: status {claim.status!r} not in {', '.join(STATUSES)}")
            continue
        if not claim.scope or claim.scope in _EMPTY:
            report.problems.append(f"{where}: scope and caveats must be stated")
        if claim.status in EVIDENCE_REQUIRED and (not claim.experiment or not claim.checks):
            report.problems.append(f"{where}: {claim.status} needs an experiment ID and at least one check")
            continue
        if not claim.experiment:
            if claim.checks:
                report.problems.append(f"{where}: checks given without an experiment")
            continue
        if claim.experiment not in cache:
            raw_dir = raw_root / claim.experiment
            manifest_path, metrics_path = raw_dir / "manifest.json", raw_dir / "metrics.json"
            if not (manifest_path.is_file() and metrics_path.is_file()):
                cache[claim.experiment] = None
            else:
                cache[claim.experiment] = (
                    json.loads(manifest_path.read_text(encoding="utf-8")),
                    json.loads(metrics_path.read_text(encoding="utf-8")),
                )
                if require_committed and not (_tracked(manifest_path) and _tracked(metrics_path)):
                    report.problems.append(f"{where}: raw results for {claim.experiment} are not committed")
        loaded = cache[claim.experiment]
        if loaded is None:
            report.problems.append(f"{where}: no raw results at {raw_root / claim.experiment}")
            continue
        manifest, metrics = loaded
        if claim.status == "SUPPORTED":
            if manifest.get("git_dirty") is not False:
                report.problems.append(f"{where}: SUPPORTED needs a run from a clean tree (git_dirty is "
                                       f"{manifest.get('git_dirty')!r})")
            if "holdout" in (manifest.get("splits_evaluated") or []) or "development" in (
                manifest.get("splits_evaluated") or []
            ):
                report.problems.append(f"{where}: SUPPORTED claims must rest on the test split only")
        for check in claim.checks:
            passed, detail = evaluate_check(metrics, check)
            if passed:
                report.checks_passed += 1
            else:
                report.problems.append(f"{where}: check failed: {check} ({detail})")
    if manuscript_text is not None:
        for cited in sorted(set(_CITE_RE.findall(manuscript_text)) - seen):
            report.problems.append(f"manuscript cites [{cited}], which is not in the claim registry")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claims", type=Path, default=CLAIMS_PATH)
    parser.add_argument("--manuscript", type=Path, default=MANUSCRIPT_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_DIR)
    parser.add_argument("--require-committed", action="store_true", help="cited raw results must be tracked by git")
    args = parser.parse_args(argv)
    manuscript = args.manuscript.read_text(encoding="utf-8") if args.manuscript.is_file() else None
    report = check_registry(
        args.claims.read_text(encoding="utf-8"), raw_root=args.raw_root, manuscript_text=manuscript,
        require_committed=args.require_committed,
    )
    counts = {s: sum(1 for c in report.claims if c.status == s) for s in STATUSES}
    print(f"{len(report.claims)} claims: " + ", ".join(f"{s} {n}" for s, n in counts.items())
          + f"; {report.checks_passed} checks passed")
    for problem in report.problems:
        print(f"PROBLEM: {problem}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

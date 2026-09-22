"""Load golden benchmark cases from JSON."""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import BenchmarkCase


def load_case(path: Path) -> BenchmarkCase:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return BenchmarkCase.from_dict(data)


def load_suite(cases_dir: Path) -> list[BenchmarkCase]:
    root = Path(cases_dir)
    files = sorted(root.rglob("*.json"))
    cases: list[BenchmarkCase] = []
    for path in files:
        if path.name.startswith("_"):
            continue
        if "baselines" in path.parts:
            continue
        cases.append(load_case(path))
    # stable ID uniqueness
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise ValueError(f"duplicate case_id: {case.case_id}")
        seen.add(case.case_id)
    return cases


def filter_cases(
    cases: list[BenchmarkCase],
    *,
    case_id: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    required: bool | None = None,
) -> list[BenchmarkCase]:
    out = list(cases)
    if case_id:
        out = [c for c in out if c.case_id == case_id]
    if category:
        out = [c for c in out if c.category.upper() == category.upper()]
    if tag:
        out = [c for c in out if tag in c.tags]
    if required is not None:
        out = [c for c in out if c.required is required]
    return out

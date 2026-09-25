"""Canonical service modules must not import experimental modules."""

from __future__ import annotations

import ast
from pathlib import Path

from ci_failure_orchestrator import module_status as ms

PACKAGE = "ci_failure_orchestrator"
PACKAGE_DIR = Path(__file__).resolve().parents[1] / PACKAGE
MAX_CANONICAL_LINES = 1000


def _top_level_entries() -> set[str]:
    entries = {p.stem for p in PACKAGE_DIR.glob("*.py")}
    entries |= {p.name for p in PACKAGE_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    return entries


def _module_parts(path: Path) -> list[str]:
    rel = path.relative_to(PACKAGE_DIR).with_suffix("")
    return [PACKAGE, *rel.parts]


def imported_modules(source: str, module_parts: list[str]) -> set[str]:
    """Absolute dotted names of package modules imported by a module (inline imports included)."""
    package_parts = module_parts[:-1]
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names if a.name.split(".")[0] == PACKAGE}
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module and node.module.split(".")[0] == PACKAGE:
                    found.add(node.module)
                    found |= {f"{node.module}.{a.name}" for a in node.names}
                continue
            base = package_parts[: len(package_parts) - (node.level - 1)]
            if node.module:
                target = [*base, *node.module.split(".")]
                found.add(".".join(target))
                found |= {".".join([*target, a.name]) for a in node.names}
            else:
                found |= {".".join([*base, a.name]) for a in node.names}
    return found


def _top_level(dotted: str) -> str | None:
    parts = dotted.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == PACKAGE else None


def _canonical_files() -> list[Path]:
    files: list[Path] = []
    for entry in sorted(ms.CANONICAL):
        path = PACKAGE_DIR / entry
        if path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
        else:
            files.append(path.with_suffix(".py"))
    return files


def _boundary_edges() -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for path in _canonical_files():
        parts = _module_parts(path)
        source_id = ".".join(p for p in parts[1:] if p != "__init__") or "__init__"
        for dotted in imported_modules(path.read_text(encoding="utf-8"), parts):
            top = _top_level(dotted)
            if top is not None and ms.status_of(top) == "experimental":
                edges.add((source_id, top))
    return edges


def test_every_module_is_classified():
    unclassified = sorted(e for e in _top_level_entries() if ms.status_of(e) is None)
    assert unclassified == [], f"classify these in module_status.py: {unclassified}"


def test_manifest_entries_exist():
    declared = set(ms.CANONICAL) | set(ms.ENTRYPOINTS)
    for members in ms.EXPERIMENTAL.values():
        declared |= members
    assert sorted(declared - _top_level_entries()) == []


def test_classification_is_disjoint():
    seen: dict[str, str] = {}
    buckets = {"canonical": ms.CANONICAL, "entrypoint": ms.ENTRYPOINTS, **ms.EXPERIMENTAL}
    for bucket, members in buckets.items():
        for name in members:
            assert name not in seen, f"{name} in both {seen[name]} and {bucket}"
            seen[name] = bucket


def test_canonical_modules_do_not_import_experimental():
    edges = _boundary_edges()
    new = sorted(edges - ms.KNOWN_BOUNDARY_VIOLATIONS)
    stale = sorted(ms.KNOWN_BOUNDARY_VIOLATIONS - edges)
    assert new == [], f"new canonical->experimental imports: {new}"
    assert stale == [], f"remove fixed entries from KNOWN_BOUNDARY_VIOLATIONS: {stale}"


def test_canonical_files_stay_under_line_limit():
    over = {}
    for path in _canonical_files():
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > MAX_CANONICAL_LINES:
            over[path.relative_to(PACKAGE_DIR).as_posix()] = lines
    assert over == {}


def test_checker_detects_relative_absolute_and_inline_imports():
    source = (
        "from ..graph import PipelineGraph\n"
        "import ci_failure_orchestrator.trust\n"
        "def f():\n"
        "    from ci_failure_orchestrator.supervisor import X\n"
        "from . import models\n"
    )
    found = imported_modules(source, [PACKAGE, "foundation", "example"])
    tops = {_top_level(d) for d in found}
    assert {"graph", "trust", "supervisor", "foundation"} <= tops
    assert f"{PACKAGE}.foundation.models" in found


def test_checker_resolves_top_level_relative_imports():
    found = imported_modules("from .graph import G\n", [PACKAGE, "repo_fix"])
    assert f"{PACKAGE}.graph" in found

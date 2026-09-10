from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath

from .github_client import RepositoryEvidence

_SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs"}
_TEST_MARKERS = ("tests/", "test/")


def _blob_paths(evidence: RepositoryEvidence) -> list[str]:
    return sorted(
        item["path"] for item in evidence.tree
        if item.get("type") == "blob" and item.get("path")
    )


def _is_source(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in _SOURCE_SUFFIXES and not _is_test(path)


def _is_test(path: str) -> bool:
    lower = path.lower()
    name = PurePosixPath(path).name.lower()
    return (
        lower.startswith(_TEST_MARKERS)
        or name.startswith("test_")
        or name.endswith(("_test.py", ".test.js", ".test.ts", ".test.tsx", ".spec.js", ".spec.ts", ".spec.tsx"))
    )


def _component(path: str) -> str:
    parts = PurePosixPath(path).parts
    if not parts:
        return "."
    if parts[0] in {"src", "lib", "app", "packages"} and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def build_architecture_graph(evidence: RepositoryEvidence) -> dict:
    """Infer a deterministic file/component graph from repository layout.

    This is intentionally structural rather than semantic: no LLM inference is
    used and source contents are not required.
    """
    paths = _blob_paths(evidence)
    source_paths = [p for p in paths if _is_source(p)]
    test_paths = [p for p in paths if _is_test(p)]

    components: dict[str, dict] = {}
    source_by_stem: dict[str, list[str]] = defaultdict(list)
    for path in source_paths:
        comp = _component(path)
        entry = components.setdefault(comp, {"source_files": 0, "test_files": 0, "languages": Counter()})
        entry["source_files"] += 1
        entry["languages"][PurePosixPath(path).suffix.lower()] += 1
        source_by_stem[PurePosixPath(path).stem.lower()].append(path)

    test_links: list[dict] = []
    for path in test_paths:
        comp = _component(path)
        entry = components.setdefault(comp, {"source_files": 0, "test_files": 0, "languages": Counter()})
        entry["test_files"] += 1
        stem = PurePosixPath(path).stem.lower()
        if stem.startswith("test_"):
            stem = stem[len("test_"):]
        for suffix in ("_test", ".test", ".spec"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
        candidates = source_by_stem.get(stem, [])
        test_links.append({"test": path, "source_candidates": candidates[:10]})

    normalized_components = {
        name: {
            "source_files": value["source_files"],
            "test_files": value["test_files"],
            "languages": dict(sorted(value["languages"].items())),
        }
        for name, value in sorted(components.items())
    }
    covered_sources = {src for link in test_links for src in link["source_candidates"]}
    return {
        "components": normalized_components,
        "source_files": len(source_paths),
        "test_files": len(test_paths),
        "test_links": test_links,
        "structurally_test_mapped_sources": len(covered_sources),
        "structural_test_mapping_ratio": round(len(covered_sources) / len(source_paths), 4) if source_paths else None,
    }


def _workflow_trigger(content: str, trigger: str) -> bool:
    lower = content.lower()
    nested = bool(re.search(rf"(?m)^\s*{re.escape(trigger)}\s*:", lower))
    compact = bool(re.search(rf"(?m)^\s*on\s*:\s*{re.escape(trigger)}\s*$", lower))
    bracketed = bool(re.search(rf"(?m)^\s*on\s*:\s*\[[^\]]*\b{re.escape(trigger)}\b[^\]]*\]\s*$", lower))
    return nested or compact or bracketed


def analyze_workflow_semantics(evidence: RepositoryEvidence) -> dict:
    workflows = {
        path: content
        for path, content in evidence.files.items()
        if path.lower().startswith(".github/workflows/") and path.lower().endswith((".yml", ".yaml"))
    }
    details: list[dict] = []
    aggregate = Counter()
    for path, content in sorted(workflows.items()):
        lower = content.lower()
        signals = {
            "pull_request_trigger": _workflow_trigger(content, "pull_request"),
            "push_trigger": _workflow_trigger(content, "push"),
            "scheduled": bool(re.search(r"(?m)^\s*schedule\s*:", lower)),
            "tests": any(token in lower for token in ("pytest", "npm test", "pnpm test", "go test", "cargo test", "dotnet test", "mvn test", "gradle test")),
            "static_analysis": any(token in lower for token in ("ruff", "flake8", "mypy", "eslint", "sonarqube", "sonarcloud", "golangci-lint", "clippy")),
            "security": any(token in lower for token in ("codeql", "bandit", "semgrep", "trivy", "snyk", "pip-audit", "npm audit", "dependabot")),
            "coverage": any(token in lower for token in ("coverage", "codecov", "coveralls", "--cov")),
            "artifact": "upload-artifact" in lower,
        }
        aggregate.update(key for key, value in signals.items() if value)
        details.append({"path": path, **signals})
    return {"workflow_count": len(details), "signals": dict(sorted(aggregate.items())), "workflows": details}


def analyze_dependencies(evidence: RepositoryEvidence) -> dict:
    manifests = {}
    dependency_names: set[str] = set()
    for path, content in sorted(evidence.files.items()):
        name = PurePosixPath(path).name.lower()
        if name == "requirements.txt":
            deps = []
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith(("-r", "--")):
                    continue
                dep = re.split(r"[<>=!~\[;\s]", line, maxsplit=1)[0].strip()
                if dep:
                    deps.append(dep)
            manifests[path] = sorted(set(deps))
            dependency_names.update(deps)
        elif name == "pyproject.toml":
            deps = re.findall(r"[\"']([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(?:[<>=!~].*?)?[\"']", content)
            ignored = {"name", "version", "description", "python", "readme", "license"}
            deps = sorted({d for d in deps if d.lower() not in ignored})
            manifests[path] = deps
            dependency_names.update(deps)
        elif name == "package.json":
            blocks = re.findall(r'"(?:dependencies|devDependencies|peerDependencies)"\s*:\s*\{(.*?)\}', content, flags=re.S)
            deps = sorted({m.group(1) for block in blocks for m in re.finditer(r'"([^"]+)"\s*:', block)})
            manifests[path] = deps
            dependency_names.update(deps)
    return {
        "manifests_analyzed": manifests,
        "unique_dependencies_detected": len(dependency_names),
        "dependencies": sorted(dependency_names),
    }


def compute_repository_risk(*, controls: dict, architecture: dict, workflows: dict, truncated: bool) -> dict:
    """Return a transparent 0-100 risk score; higher means more engineering risk."""
    penalties: list[dict] = []

    def add(points: int, code: str, reason: str) -> None:
        penalties.append({"points": points, "code": code, "reason": reason})

    if truncated:
        add(30, "INCOMPLETE_EVIDENCE", "Repository tree is truncated; analysis cannot establish completeness.")
    for key, points in (("ci_workflow", 20), ("tests", 20), ("build_manifest", 10), ("security_policy", 5), ("codeowners", 5), ("dependabot", 4), ("pre_commit", 3), ("readme", 3)):
        if not controls.get(key):
            add(points, f"MISSING_{key.upper()}", f"Repository control '{key}' is absent.")

    signals = workflows.get("signals", {})
    if controls.get("ci_workflow"):
        if not signals.get("tests"):
            add(10, "CI_NO_TEST_SIGNAL", "No recognized automated test command was found in fetched workflows.")
        if not signals.get("security"):
            add(5, "CI_NO_SECURITY_SIGNAL", "No recognized security scanner was found in fetched workflows.")
        if not signals.get("static_analysis"):
            add(5, "CI_NO_STATIC_ANALYSIS", "No recognized static-analysis command was found in fetched workflows.")

    ratio = architecture.get("structural_test_mapping_ratio")
    if architecture.get("source_files", 0) >= 5 and ratio is not None and ratio < 0.2:
        add(5, "LOW_STRUCTURAL_TEST_MAPPING", "Few source files have convention-based test counterparts.")

    score = min(100, sum(item["points"] for item in penalties))
    band = "LOW" if score <= 20 else "MODERATE" if score <= 45 else "HIGH" if score <= 70 else "CRITICAL"
    return {"score": score, "band": band, "penalties": penalties}


def build_engineering_intelligence(evidence: RepositoryEvidence, controls: dict) -> dict:
    architecture = build_architecture_graph(evidence)
    workflows = analyze_workflow_semantics(evidence)
    dependencies = analyze_dependencies(evidence)
    risk = compute_repository_risk(
        controls=controls,
        architecture=architecture,
        workflows=workflows,
        truncated=evidence.truncated,
    )
    return {
        "architecture": architecture,
        "workflow_semantics": workflows,
        "dependencies": dependencies,
        "risk": risk,
    }

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

from .engineering_intelligence import build_engineering_intelligence
from .github_client import RepositoryEvidence


@dataclass(frozen=True)
class RepositoryFinding:
    severity: str
    code: str
    message: str
    recommendation: str

    def to_dict(self) -> dict:
        return asdict(self)


def _paths(evidence: RepositoryEvidence) -> list[str]:
    return [
        item.get("path", "")
        for item in evidence.tree
        if item.get("type") == "blob" and item.get("path")
    ]


def analyze_repository(evidence: RepositoryEvidence) -> dict:
    """Produce deterministic repository health and engineering-intelligence signals."""
    paths = _paths(evidence)
    workflow_paths = sorted(
        path for path in paths if path.lower().startswith(".github/workflows/") and path.lower().endswith((".yml", ".yaml"))
    )
    test_paths = sorted(
        path
        for path in paths
        if path.lower().startswith(("tests/", "test/"))
        or PurePosixPath(path).name.lower().startswith("test_")
        or PurePosixPath(path).name.lower().endswith(("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts"))
    )
    docs_paths = sorted(path for path in paths if path.lower().startswith("docs/"))

    manifest_names = {
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "go.mod",
        "cargo.toml",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
    }
    manifest_paths = sorted(path for path in paths if PurePosixPath(path).name.lower() in manifest_names)

    has_readme = any(PurePosixPath(path).name.lower().startswith("readme") for path in paths)
    has_security = any(path.lower().endswith("security.md") for path in paths)
    has_codeowners = any(PurePosixPath(path).name.lower() == "codeowners" for path in paths)
    has_dependabot = any(PurePosixPath(path).name.lower() in {"dependabot.yml", "dependabot.yaml"} for path in paths)
    has_precommit = any(PurePosixPath(path).name.lower() in {".pre-commit-config.yml", ".pre-commit-config.yaml"} for path in paths)

    controls = {
        "readme": has_readme,
        "security_policy": has_security,
        "codeowners": has_codeowners,
        "dependabot": has_dependabot,
        "pre_commit": has_precommit,
        "ci_workflow": bool(workflow_paths),
        "tests": bool(test_paths),
        "build_manifest": bool(manifest_paths),
    }

    findings: list[RepositoryFinding] = []
    if evidence.truncated:
        findings.append(
            RepositoryFinding(
                "high",
                "TREE_TRUNCATED",
                "GitHub reported a truncated recursive tree, so the repository inventory is incomplete.",
                "Use subtree pagination before making a complete repository-health claim.",
            )
        )
    if not workflow_paths:
        findings.append(
            RepositoryFinding(
                "high",
                "NO_CI_WORKFLOW",
                "No GitHub Actions workflow was detected.",
                "Add CI covering tests, static analysis, security checks, and policy gates.",
            )
        )
    if not test_paths:
        findings.append(
            RepositoryFinding(
                "high",
                "NO_TESTS_DETECTED",
                "No conventional test files were detected.",
                "Add an automated test suite and require it in CI.",
            )
        )
    if not manifest_paths:
        findings.append(
            RepositoryFinding(
                "medium",
                "NO_BUILD_MANIFEST",
                "No recognized build or dependency manifest was detected.",
                "Declare reproducible dependencies and build metadata in a standard manifest.",
            )
        )
    if not has_security:
        findings.append(
            RepositoryFinding(
                "medium",
                "NO_SECURITY_POLICY",
                "No SECURITY.md policy was detected.",
                "Add a security policy covering reporting and supported versions.",
            )
        )
    if not has_codeowners:
        findings.append(
            RepositoryFinding(
                "medium",
                "NO_CODEOWNERS",
                "No CODEOWNERS file was detected.",
                "Define ownership for critical paths and pair it with required review policy.",
            )
        )
    if not has_dependabot:
        findings.append(
            RepositoryFinding(
                "low",
                "NO_DEPENDABOT",
                "No Dependabot configuration was detected.",
                "Enable automated dependency update proposals or document an equivalent control.",
            )
        )
    if not has_precommit:
        findings.append(
            RepositoryFinding(
                "low",
                "NO_PRECOMMIT",
                "No pre-commit configuration was detected.",
                "Consider local deterministic checks that mirror important CI gates.",
            )
        )
    if not has_readme:
        findings.append(
            RepositoryFinding(
                "low",
                "NO_README",
                "No README was detected.",
                "Add problem statement, architecture, setup, verification, and operational limitations.",
            )
        )

    engineering = build_engineering_intelligence(evidence, controls)
    risk = engineering["risk"]
    high = sum(f.severity == "high" for f in findings)
    medium = sum(f.severity == "medium" for f in findings)
    status = "REPO_HEALTHY" if high == 0 and medium == 0 and risk["score"] <= 20 else "NEEDS_ACTION"

    return {
        "repository": evidence.metadata.get("full_name"),
        "default_branch": evidence.metadata.get("default_branch"),
        "inventory": {
            "files": len(paths),
            "tree_truncated": evidence.truncated,
            "workflows": workflow_paths,
            "tests_detected": len(test_paths),
            "docs_detected": len(docs_paths),
            "manifests": manifest_paths,
            "evidence_files_fetched": sorted(evidence.files),
        },
        "controls": controls,
        "engineering_intelligence": engineering,
        "findings": [finding.to_dict() for finding in findings],
        "summary": {
            "high": high,
            "medium": medium,
            "low": sum(f.severity == "low" for f in findings),
            "risk_score": risk["score"],
            "risk_band": risk["band"],
        },
        "repo_status": status,
    }

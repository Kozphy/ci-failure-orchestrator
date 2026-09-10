from ci_failure_orchestrator.github_client import RepositoryEvidence
from ci_failure_orchestrator.repository_analysis import analyze_repository


def make_evidence(paths, *, truncated=False):
    return RepositoryEvidence(
        metadata={"full_name": "owner/repo", "default_branch": "main"},
        tree=[{"path": path, "type": "blob"} for path in paths],
        files={},
        truncated=truncated,
    )


def test_repository_with_core_controls_is_healthy():
    evidence = make_evidence(
        [
            "README.md",
            "SECURITY.md",
            ".github/CODEOWNERS",
            ".github/dependabot.yml",
            ".pre-commit-config.yaml",
            ".github/workflows/ci.yml",
            "pyproject.toml",
            "tests/test_cli.py",
            "docs/architecture.md",
        ]
    )

    result = analyze_repository(evidence)

    assert result["repo_status"] == "REPO_HEALTHY"
    assert result["summary"] == {"high": 0, "medium": 0, "low": 0}
    assert result["controls"]["ci_workflow"] is True
    assert result["controls"]["tests"] is True


def test_repository_missing_ci_and_tests_needs_action():
    result = analyze_repository(make_evidence(["README.md", "pyproject.toml"]))

    assert result["repo_status"] == "NEEDS_ACTION"
    assert result["summary"]["high"] == 2
    codes = {finding["code"] for finding in result["findings"]}
    assert "NO_CI_WORKFLOW" in codes
    assert "NO_TESTS_DETECTED" in codes


def test_truncated_tree_is_high_severity():
    result = analyze_repository(
        make_evidence(
            [
                "README.md",
                "SECURITY.md",
                ".github/CODEOWNERS",
                ".github/dependabot.yml",
                ".pre-commit-config.yaml",
                ".github/workflows/ci.yml",
                "pyproject.toml",
                "tests/test_cli.py",
            ],
            truncated=True,
        )
    )

    assert result["repo_status"] == "NEEDS_ACTION"
    assert any(finding["code"] == "TREE_TRUNCATED" for finding in result["findings"])

from ci_failure_orchestrator.github_client import RepositoryEvidence
from ci_failure_orchestrator.repository_analysis import analyze_repository


def make_evidence(paths, *, files=None, truncated=False):
    return RepositoryEvidence(
        metadata={"full_name": "owner/repo", "default_branch": "main"},
        tree=[{"path": path, "type": "blob"} for path in paths],
        files=files or {},
        truncated=truncated,
    )


def test_repository_with_core_controls_is_healthy():
    paths = [
        "README.md",
        "SECURITY.md",
        ".github/CODEOWNERS",
        ".github/dependabot.yml",
        ".pre-commit-config.yaml",
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "ci_failure_orchestrator/cli.py",
        "tests/test_cli.py",
        "docs/architecture.md",
    ]
    files = {
        ".github/workflows/ci.yml": "on: [push, pull_request]\njobs:\n  test:\n    steps:\n      - run: pytest --cov=ci_failure_orchestrator\n      - run: ruff check .\n      - run: pip-audit\n",
        "pyproject.toml": '[project]\nname="demo"\ndependencies=["requests>=2", "pydantic>=2"]\n',
    }
    result = analyze_repository(make_evidence(paths, files=files))

    assert result["repo_status"] == "REPO_HEALTHY"
    assert result["summary"]["high"] == 0
    assert result["summary"]["medium"] == 0
    assert result["summary"]["low"] == 0
    assert result["summary"]["risk_band"] == "LOW"
    assert result["controls"]["ci_workflow"] is True
    assert result["controls"]["tests"] is True

    intelligence = result["engineering_intelligence"]
    assert intelligence["architecture"]["source_files"] == 1
    assert intelligence["architecture"]["structurally_test_mapped_sources"] == 1
    assert intelligence["workflow_semantics"]["signals"]["pull_request_trigger"] == 1
    assert intelligence["workflow_semantics"]["signals"]["push_trigger"] == 1
    assert intelligence["workflow_semantics"]["signals"]["tests"] == 1
    assert intelligence["workflow_semantics"]["signals"]["static_analysis"] == 1
    assert intelligence["workflow_semantics"]["signals"]["security"] == 1
    assert "requests" in intelligence["dependencies"]["dependencies"]


def test_repository_missing_ci_and_tests_needs_action():
    result = analyze_repository(make_evidence(["README.md", "pyproject.toml"]))

    assert result["repo_status"] == "NEEDS_ACTION"
    assert result["summary"]["high"] == 2
    assert result["summary"]["risk_score"] >= 40
    codes = {finding["code"] for finding in result["findings"]}
    assert "NO_CI_WORKFLOW" in codes
    assert "NO_TESTS_DETECTED" in codes


def test_truncated_tree_is_high_severity_and_high_risk():
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
    assert result["summary"]["risk_score"] >= 30
    assert any(finding["code"] == "TREE_TRUNCATED" for finding in result["findings"])


def test_workflow_without_quality_gates_increases_risk():
    paths = [
        "README.md",
        "SECURITY.md",
        ".github/CODEOWNERS",
        ".github/dependabot.yml",
        ".pre-commit-config.yaml",
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "src/app.py",
        "src/service.py",
        "src/store.py",
        "src/policy.py",
        "src/api.py",
        "tests/test_unrelated.py",
    ]
    result = analyze_repository(
        make_evidence(paths, files={".github/workflows/ci.yml": "on: push\njobs:\n  build:\n    steps:\n      - run: python -m build\n"})
    )

    penalties = {item["code"] for item in result["engineering_intelligence"]["risk"]["penalties"]}
    assert "CI_NO_TEST_SIGNAL" in penalties
    assert "CI_NO_SECURITY_SIGNAL" in penalties
    assert "CI_NO_STATIC_ANALYSIS" in penalties
    assert "LOW_STRUCTURAL_TEST_MAPPING" in penalties
    assert result["repo_status"] == "NEEDS_ACTION"

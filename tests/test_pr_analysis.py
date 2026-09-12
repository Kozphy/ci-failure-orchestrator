from ci_failure_orchestrator.github_client import PullRequestEvidence
from ci_failure_orchestrator.pr_analysis import analyze_pull_request


def make_evidence(*, changed_files=None, reviews=None, workflow_runs=None, commit_state="success"):
    return PullRequestEvidence(
        metadata={
            "number": 42,
            "title": "change",
            "state": "open",
            "draft": False,
            "head": {"sha": "abc", "ref": "feature"},
            "base": {"ref": "main"},
        },
        changed_files=changed_files or [],
        reviews=reviews or [],
        commit_status={"state": commit_state},
        workflow_runs=workflow_runs or [],
    )


def successful_run(name="ci"):
    return {"name": name, "status": "completed", "conclusion": "success"}


def test_docs_only_change_with_green_ci_is_ready():
    result = analyze_pull_request(
        make_evidence(
            changed_files=[{"filename": "docs/guide.md", "additions": 10, "deletions": 1}],
            workflow_runs=[successful_run()],
        )
    )
    assert result["pr_decision"] == "PR_READY"
    assert result["blockers"] == []


def test_source_change_without_tests_blocks():
    result = analyze_pull_request(
        make_evidence(
            changed_files=[{"filename": "src/service.py", "additions": 20, "deletions": 2}],
            workflow_runs=[successful_run()],
        )
    )
    assert result["pr_decision"] == "BLOCK"
    assert any(item["code"] == "SOURCE_CHANGE_WITHOUT_TEST_CHANGE" for item in result["blockers"])


def test_source_and_test_change_can_pass_with_green_ci():
    result = analyze_pull_request(
        make_evidence(
            changed_files=[
                {"filename": "src/service.py", "additions": 20, "deletions": 2},
                {"filename": "tests/test_service.py", "additions": 15, "deletions": 0},
            ],
            workflow_runs=[successful_run()],
        )
    )
    assert result["pr_decision"] == "PR_READY"


def test_changes_requested_blocks_even_when_ci_green():
    result = analyze_pull_request(
        make_evidence(
            changed_files=[{"filename": "docs/guide.md", "additions": 2, "deletions": 0}],
            reviews=[{"user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED"}],
            workflow_runs=[successful_run()],
        )
    )
    assert result["pr_decision"] == "BLOCK"
    assert any(item["code"] == "CHANGES_REQUESTED" for item in result["blockers"])


def test_pending_ci_fails_closed():
    result = analyze_pull_request(
        make_evidence(
            changed_files=[{"filename": "docs/guide.md", "additions": 2, "deletions": 0}],
            workflow_runs=[{"name": "ci", "status": "in_progress", "conclusion": None}],
            commit_state="pending",
        )
    )
    assert result["pr_decision"] == "BLOCK"
    assert result["ci_evidence"]["state"] == "PENDING"


def test_security_sensitive_change_requires_approval():
    result = analyze_pull_request(
        make_evidence(
            changed_files=[
                {"filename": "ci_failure_orchestrator/policy.py", "additions": 4, "deletions": 1},
                {"filename": "tests/test_policy.py", "additions": 4, "deletions": 0},
            ],
            workflow_runs=[successful_run()],
        )
    )
    assert result["pr_decision"] == "BLOCK"
    assert any(item["code"] == "SECURITY_SENSITIVE_CHANGE_UNAPPROVED" for item in result["blockers"])


def test_security_sensitive_change_with_approval_can_pass():
    result = analyze_pull_request(
        make_evidence(
            changed_files=[
                {"filename": "ci_failure_orchestrator/policy.py", "additions": 4, "deletions": 1},
                {"filename": "tests/test_policy.py", "additions": 4, "deletions": 0},
            ],
            reviews=[{"user": {"login": "reviewer"}, "state": "APPROVED"}],
            workflow_runs=[successful_run()],
        )
    )
    assert result["pr_decision"] == "PR_READY"

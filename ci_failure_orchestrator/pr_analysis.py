from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath

from .github_client import PullRequestEvidence

_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".cs"}
_TEST_SUFFIXES = ("_test.py", ".test.js", ".test.ts", ".test.tsx", ".spec.js", ".spec.ts", ".spec.tsx")
_MANIFESTS = {"pyproject.toml", "requirements.txt", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "pipfile", "go.mod", "go.sum", "cargo.toml", "cargo.lock"}
_SECURITY_PATH_MARKERS = ("security", "auth", "permission", "policy", "secret", "crypto", "iam", "rbac")


def _is_test(path: str) -> bool:
    lower = path.lower()
    name = PurePosixPath(lower).name
    return lower.startswith(("tests/", "test/")) or name.startswith("test_") or name.endswith(_TEST_SUFFIXES)


def _is_source(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in _SOURCE_SUFFIXES and not _is_test(path)


def _classify_changed_files(changed_files: list[dict]) -> dict:
    paths = [item.get("filename", "") for item in changed_files if item.get("filename")]
    source = sorted(p for p in paths if _is_source(p))
    tests = sorted(p for p in paths if _is_test(p))
    workflows = sorted(p for p in paths if p.lower().startswith(".github/workflows/"))
    manifests = sorted(p for p in paths if PurePosixPath(p).name.lower() in _MANIFESTS)
    docs = sorted(p for p in paths if p.lower().startswith("docs/") or PurePosixPath(p).suffix.lower() in {".md", ".rst"})
    security_sensitive = sorted(
        p for p in paths if any(marker in p.lower() for marker in _SECURITY_PATH_MARKERS)
    )
    additions = sum(int(item.get("additions") or 0) for item in changed_files)
    deletions = sum(int(item.get("deletions") or 0) for item in changed_files)
    return {
        "files": len(paths),
        "paths": sorted(paths),
        "source": source,
        "tests": tests,
        "workflows": workflows,
        "manifests": manifests,
        "docs": docs,
        "security_sensitive": security_sensitive,
        "additions": additions,
        "deletions": deletions,
        "changed_lines": additions + deletions,
    }


def _review_state(reviews: list[dict]) -> dict:
    latest_by_user: dict[str, dict] = {}
    for review in reviews:
        user = ((review.get("user") or {}).get("login")) or "unknown"
        latest_by_user[user] = review
    states = Counter(str(review.get("state") or "UNKNOWN").upper() for review in latest_by_user.values())
    return {
        "latest_reviewers": len(latest_by_user),
        "approvals": states.get("APPROVED", 0),
        "changes_requested": states.get("CHANGES_REQUESTED", 0),
        "comments": states.get("COMMENTED", 0),
        "states": dict(sorted(states.items())),
    }


def _ci_state(evidence: PullRequestEvidence) -> dict:
    runs = evidence.workflow_runs
    status_state = str(evidence.commit_status.get("state") or "").lower()
    run_conclusions = Counter(str(run.get("conclusion") or "PENDING").upper() for run in runs)
    run_statuses = Counter(str(run.get("status") or "UNKNOWN").upper() for run in runs)

    failing = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
    has_failure = any(run_conclusions.get(name, 0) for name in failing) or status_state in {"failure", "error"}
    has_pending = any((run.get("status") or "").lower() != "completed" for run in runs) or status_state == "pending"
    completed_runs = [run for run in runs if (run.get("status") or "").lower() == "completed"]
    successful_runs = [run for run in completed_runs if (run.get("conclusion") or "").lower() in {"success", "neutral", "skipped"}]

    if has_failure:
        state = "FAIL"
    elif has_pending:
        state = "PENDING"
    elif not runs and status_state not in {"success"}:
        state = "NO_EVIDENCE"
    elif runs and len(successful_runs) != len(completed_runs):
        state = "FAIL"
    else:
        state = "PASS"

    return {
        "state": state,
        "combined_commit_status": status_state or None,
        "workflow_runs": len(runs),
        "run_statuses": dict(sorted(run_statuses.items())),
        "run_conclusions": dict(sorted(run_conclusions.items())),
    }


def analyze_pull_request(evidence: PullRequestEvidence) -> dict:
    """Evaluate change risk and produce a fail-closed PR readiness decision."""
    changed = _classify_changed_files(evidence.changed_files)
    reviews = _review_state(evidence.reviews)
    ci = _ci_state(evidence)

    findings: list[dict] = []

    def add(severity: str, code: str, message: str, recommendation: str) -> None:
        findings.append({
            "severity": severity,
            "code": code,
            "message": message,
            "recommendation": recommendation,
        })

    if changed["source"] and not changed["tests"]:
        add(
            "high",
            "SOURCE_CHANGE_WITHOUT_TEST_CHANGE",
            "Source files changed but no conventional test file changed in this PR.",
            "Add or update tests, or supply independent evidence that existing tests fully exercise the change.",
        )
    if changed["security_sensitive"] and reviews["approvals"] == 0:
        add(
            "high",
            "SECURITY_SENSITIVE_CHANGE_UNAPPROVED",
            "Security/policy-sensitive paths changed without an approving review.",
            "Require an independent reviewer before treating the PR as ready.",
        )
    if changed["workflows"]:
        add(
            "medium",
            "CI_WORKFLOW_CHANGED",
            "The PR changes CI workflow definitions.",
            "Verify the workflow itself through an independent run and review permissions/triggers carefully.",
        )
    if changed["manifests"]:
        add(
            "medium",
            "DEPENDENCY_OR_BUILD_CHANGE",
            "The PR changes dependency/build manifests.",
            "Review dependency provenance, lockfile consistency, and security scanner results.",
        )
    if changed["changed_lines"] > 1000:
        add(
            "medium",
            "LARGE_CHANGESET",
            f"The PR changes {changed['changed_lines']} lines, increasing review complexity.",
            "Split unrelated changes or add stronger targeted verification evidence.",
        )
    if reviews["changes_requested"]:
        add(
            "high",
            "CHANGES_REQUESTED",
            "At least one reviewer's latest state requests changes.",
            "Resolve the review findings and obtain a new review state.",
        )
    if ci["state"] == "FAIL":
        add("high", "CI_FAILED", "Head-SHA CI evidence contains a failed check or workflow run.", "Repair the failure and rerun independent CI.")
    elif ci["state"] == "PENDING":
        add("medium", "CI_PENDING", "Required head-SHA CI evidence is still pending.", "Wait for CI to complete before merge authority is granted.")
    elif ci["state"] == "NO_EVIDENCE":
        add("high", "NO_CI_EVIDENCE", "No successful head-SHA CI evidence was found.", "Run CI on the exact PR head SHA and preserve the result as merge evidence.")

    blocking_codes = {
        "SOURCE_CHANGE_WITHOUT_TEST_CHANGE",
        "SECURITY_SENSITIVE_CHANGE_UNAPPROVED",
        "CHANGES_REQUESTED",
        "CI_FAILED",
        "CI_PENDING",
        "NO_CI_EVIDENCE",
    }
    blockers = [finding for finding in findings if finding["code"] in blocking_codes]
    decision = "PR_READY" if not blockers and ci["state"] == "PASS" else "BLOCK"

    metadata = evidence.metadata
    return {
        "pull_request": metadata.get("number"),
        "title": metadata.get("title"),
        "state": metadata.get("state"),
        "draft": bool(metadata.get("draft")),
        "head_sha": ((metadata.get("head") or {}).get("sha")),
        "base_ref": ((metadata.get("base") or {}).get("ref")),
        "head_ref": ((metadata.get("head") or {}).get("ref")),
        "change_surface": changed,
        "review_evidence": reviews,
        "ci_evidence": ci,
        "findings": findings,
        "blockers": blockers,
        "pr_decision": decision,
    }

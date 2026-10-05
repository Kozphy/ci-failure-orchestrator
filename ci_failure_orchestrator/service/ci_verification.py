"""Final verification against the real CI provider.

Local worktree evidence cannot see the real CI environment (runners, services, secrets,
matrix). After ``fix-repo-apply --push``/``--open-pr`` puts the candidate on a temporary
branch, this module reads the real CI result for that commit through a ``CIProvider`` and
re-runs the central decision with ``real_ci_passed`` set. Only then can a repair become
``VERIFIED_FIXED``.

The GitHub Actions adapter is tested against recorded API response shapes, not against the
live API. It never merges and never changes repository settings; the only write it can make
is an explicit rerun request.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from ..foundation.persistence import FileStateStore
from ..foundation.remediation import VerificationResult, decide_remediation
from ..foundation.test_evidence import TestRunSummary
from ..github_client import GitHubActionsClient, GitHubAPIError
from .common import CI_VERIFICATION_NAME, FIX_DIR, REMEDIATION_NAME, VERIFICATION_NAME
from .verification import VerificationReport, record_verification


class CIRunState(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    # Skipped or neutral: the run happened but proves nothing about the repair.
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class CIRunStatus:
    run_id: str
    state: CIRunState
    conclusion: str = ""
    name: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "state": self.state.value}


class CIProvider(Protocol):
    name: str

    def find_runs(self, commit_sha: str) -> list[str]: ...

    def rerun(self, run_id: str) -> None: ...

    def get_status(self, run_id: str) -> CIRunStatus: ...

    def get_failed_jobs(self, run_id: str) -> list[str]: ...

    def get_test_results(self, run_id: str) -> TestRunSummary | None: ...


_GITHUB_FAILED = frozenset({"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"})


class GitHubActionsCIProvider:
    """GitHub Actions adapter. Verified against recorded response shapes only, not the live API."""

    name = "github-actions"

    def __init__(self, repository: str, client: GitHubActionsClient | None = None) -> None:
        if repository.count("/") != 1:
            raise ValueError("repository must use owner/name format")
        self.repository = repository
        self.client = client or GitHubActionsClient()

    def find_runs(self, commit_sha: str) -> list[str]:
        runs = self.client.list_runs_for_commit(self.repository, commit_sha)
        return [str(run["id"]) for run in runs if run.get("id") and run.get("head_sha", commit_sha) == commit_sha]

    def rerun(self, run_id: str) -> None:
        self.client.rerun_workflow_run(self.repository, int(run_id))

    def get_status(self, run_id: str) -> CIRunStatus:
        run = self.client.get_run(self.repository, int(run_id))
        status = str(run.get("status") or "")
        conclusion = str(run.get("conclusion") or "")
        if status != "completed":
            state = CIRunState.PENDING
        elif conclusion == "success":
            state = CIRunState.SUCCESS
        elif conclusion in _GITHUB_FAILED:
            state = CIRunState.FAILURE
        else:
            state = CIRunState.SKIPPED
        return CIRunStatus(str(run_id), state, conclusion, str(run.get("name") or ""), str(run.get("html_url") or ""))

    def get_failed_jobs(self, run_id: str) -> list[str]:
        jobs = self.client.list_latest_jobs(self.repository, int(run_id))
        return [str(j.get("name") or j.get("id")) for j in jobs if j.get("conclusion") in _GITHUB_FAILED]

    def get_test_results(self, run_id: str) -> TestRunSummary | None:
        # GitHub Actions has no generic test-results API; per-test evidence stays with local verification.
        return None


def real_ci_passed(statuses: Sequence[CIRunStatus]) -> bool | None:
    """True when every finished run succeeded; None while anything is pending or nothing proves success."""
    if not statuses or any(s.state is CIRunState.PENDING for s in statuses):
        return None
    if any(s.state is CIRunState.FAILURE for s in statuses):
        return False
    if any(s.state is CIRunState.SUCCESS for s in statuses):
        return True
    return None


def verify_real_ci(
    artifacts_root: Path,
    run_id: str,
    provider: CIProvider,
    *,
    ci_run_ids: Sequence[str] = (),
    rerun: bool = False,
    wait_seconds: int = 0,
    poll_seconds: int = 15,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    artifacts_root = Path(artifacts_root)
    fix_root = artifacts_root / "runs" / run_id / FIX_DIR
    local_path = fix_root / VERIFICATION_NAME
    if not local_path.is_file():
        return {"outcome": "ERROR", "run_id": run_id, "message": "no local repair verification record for this run"}
    local = json.loads(local_path.read_text(encoding="utf-8"))
    summary = json.loads((fix_root / REMEDIATION_NAME).read_text(encoding="utf-8"))

    apply_path = artifacts_root / "runs" / run_id / "target" / "apply.json"
    commit = json.loads(apply_path.read_text(encoding="utf-8")).get("commit", "") if apply_path.is_file() else ""
    if not ci_run_ids and not commit:
        return {
            "outcome": "ERROR",
            "run_id": run_id,
            "message": "the candidate has not been applied; run fix-repo-apply --push (or pass --ci-run-id)",
        }

    ids = [str(r) for r in ci_run_ids]
    try:
        if rerun:
            for ci_run in ids:
                provider.rerun(ci_run)
        deadline = time.monotonic() + max(0, wait_seconds)
        while True:
            current = ids or provider.find_runs(commit)
            statuses = [provider.get_status(r) for r in current]
            passed = real_ci_passed(statuses)
            if passed is not None or time.monotonic() >= deadline:
                break
            sleep(poll_seconds)
        failed_jobs = {s.run_id: provider.get_failed_jobs(s.run_id) for s in statuses if s.state is CIRunState.FAILURE}
        tests = {s.run_id: provider.get_test_results(s.run_id) for s in statuses}
    except (GitHubAPIError, ValueError, KeyError) as exc:
        return {"outcome": "ERROR", "run_id": run_id, "message": f"CI provider error: {exc}"}

    runs = [s.to_dict() for s in statuses]
    if passed is None:
        return {
            "outcome": "PENDING",
            "run_id": run_id,
            "provider": provider.name,
            "commit": commit,
            "runs": runs,
            "message": "real CI has not produced a conclusive result yet; nothing was recorded",
        }

    state = FileStateStore(artifacts_root).load_run(run_id)
    previous = VerificationResult.from_dict(local["result"])
    result = VerificationResult.from_dict(
        {
            **previous.to_dict(),
            "real_ci_passed": passed,
            "human_approved": state.stop_reason == "human_approve",
        }
    )
    real_ci = {
        "provider": provider.name,
        "commit": commit,
        "runs": runs,
        "failed_jobs": failed_jobs,
        "test_results": {k: v.to_dict() if v else None for k, v in tests.items()},
    }
    report = VerificationReport(result, decide_remediation(result), {**local.get("evidence", {}), "real_ci": real_ci})
    remediation = record_verification(
        artifacts_root,
        run_id,
        report,
        stage="real_ci",
        record_name=CI_VERIFICATION_NAME,
        repair_attempt=int(summary.get("repair_attempt") or 0),
        failure_received_at=str(summary.get("failure_received_at") or ""),
        ci_green=passed,
        ci_green_source="real_ci",
    )
    return {
        "outcome": report.decision.state.value,
        "run_id": run_id,
        "real_ci_passed": passed,
        "provider": provider.name,
        "commit": commit,
        "runs": runs,
        "remediation": remediation,
    }

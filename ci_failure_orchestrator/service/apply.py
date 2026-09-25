"""fix-repo-apply: the only code path that writes to the target repository.

Requires a durable APPROVED workflow (policy or human) and creates a branch +
commit through a temporary index, never touching the operator's working tree
or current branch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..foundation.models import RunStatus
from ..foundation.persistence import (
    AuditEventType,
    FileAuditStore,
    FileEvidenceStore,
    FileStateStore,
    append_operator_event,
    verify_run_consistency,
)
from .common import FINAL_PATCH_NAME, FIX_DIR, METADATA_NAME, git
from .patches import parse_patch_files


@dataclass
class ApplyResult:
    status: str  # APPLIED | BLOCKED | PARTIAL
    run_id: str
    message: str
    repo_path: str = ""
    branch: str = ""
    commit: str = ""
    pushed: bool = False
    pr_url: str = ""
    next_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _commit_message(metadata: dict[str, Any], run_id: str, approval: str) -> str:
    summary = str(metadata.get("failure_message") or "repair failing CI check").splitlines()[0][:60]
    lines = [
        f"fix(ci): {summary}",
        "",
        f"Verified by ci-failure-orchestrator run {run_id}.",
        f"Approval: {approval}",
        "Verification commands:",
        *[f"  - {cmd}" for cmd in metadata.get("verify_commands") or []],
        f"Patch sha256: {metadata.get('patch_sha256', '')}",
    ]
    return "\n".join(lines) + "\n"


def apply_fix(
    artifacts_root: Path,
    run_id: str,
    *,
    repo_path: Path | None = None,
    branch: str | None = None,
    remote: str = "origin",
    push: bool = False,
    open_pr: bool = False,
    actor: str = "operator",
) -> ApplyResult:
    """Commit an APPROVED fix-repo patch onto a new branch of the target repository.

    Uses a temporary index (read-tree / apply --cached / commit-tree), so the
    operator's working tree, index and current branch are left untouched.
    """

    artifacts_root = Path(artifacts_root)
    run_root = artifacts_root / "runs" / run_id
    fix_root = run_root / FIX_DIR

    def blocked(message: str) -> ApplyResult:
        return ApplyResult("BLOCKED", run_id, message)

    try:
        state = FileStateStore(artifacts_root).load_run(run_id)
    except Exception as exc:  # noqa: BLE001
        return blocked(f"cannot load run: {exc}")
    report = verify_run_consistency(artifacts_root=artifacts_root, run_id=run_id, state=state)
    if not report.valid:
        return blocked("run is inconsistent: " + "; ".join(i.message for i in report.issues))
    if state.workflow_status != RunStatus.APPROVED.value:
        return blocked(
            f"fix-repo-apply requires workflow APPROVED, found {state.workflow_status}. "
            "Escalated runs need `foundation-decide --action APPROVE` first."
        )

    metadata_path = fix_root / METADATA_NAME
    patch_file = fix_root / FINAL_PATCH_NAME
    if not metadata_path.is_file() or not patch_file.is_file():
        return blocked("not a fix-repo run (fix-repo/metadata.json or final.patch missing)")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    patch_bytes = patch_file.read_bytes()
    if sha256(patch_bytes).hexdigest() != metadata.get("patch_sha256"):
        return blocked("final.patch does not match the verified patch hash")
    patch_text = patch_bytes.decode("utf-8")
    files = parse_patch_files(patch_text)
    if list(files) != list(metadata.get("files_changed") or []):
        return blocked("final.patch files do not match the verified file list")

    events, _ = FileAuditStore(artifacts_root).read_events_tolerant(run_id)
    if any(e.event_type == AuditEventType.TARGET_PATCH_APPLIED.value for e in events):
        return blocked("this run's patch was already applied to the target repository")

    repo = Path(repo_path or metadata.get("repo_path") or "").resolve()
    if not (repo / ".git").exists():
        return blocked(f"not a git repository: {repo}")
    base_commit = str(metadata.get("base_commit") or "")
    if git(repo, "cat-file", "-e", f"{base_commit}^{{commit}}").returncode != 0:
        return blocked(f"base commit {base_commit} not found in {repo}")

    branch_name = branch or f"ci-orchestrator/fix-{run_id}"
    if git(repo, "check-ref-format", "--branch", branch_name).returncode != 0:
        return blocked(f"invalid branch name: {branch_name}")
    if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch_name}").returncode == 0:
        return blocked(f"branch already exists: {branch_name}")

    approval = (
        f"human APPROVE ({state.stop_reason})" if state.stop_reason == "human_approve" else "policy APPROVE"
    )

    with tempfile.TemporaryDirectory(prefix="ci-orchestrator-apply-") as temp_dir:
        tmp = Path(temp_dir)
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(tmp / "index")
        (tmp / "fix.patch").write_bytes(patch_bytes)
        (tmp / "message.txt").write_bytes(_commit_message(metadata, run_id, approval).encode("utf-8"))

        steps = (
            ("read-tree", ("read-tree", base_commit)),
            ("apply", ("apply", "--cached", "--whitespace=nowarn", str(tmp / "fix.patch"))),
        )
        for label, args in steps:
            done = git(repo, *args, env=env)
            if done.returncode != 0:
                return blocked(f"git {label} failed: {done.stderr.strip()[:500]}")
        tree = git(repo, "write-tree", env=env)
        if tree.returncode != 0:
            return blocked(f"git write-tree failed: {tree.stderr.strip()[:500]}")
        commit = git(repo, "commit-tree", tree.stdout.strip(), "-p", base_commit, "-F", str(tmp / "message.txt"), env=env)
        if commit.returncode != 0:
            return blocked(f"git commit-tree failed (is user.name/user.email configured?): {commit.stderr.strip()[:500]}")
    commit_sha = commit.stdout.strip()

    diff_names = {
        line for line in git(repo, "diff", "--name-only", base_commit, commit_sha).stdout.splitlines() if line
    }
    if not diff_names or not diff_names <= set(files):
        return blocked(f"commit contents do not match the verified patch: {sorted(diff_names)}")

    created = git(repo, "update-ref", f"refs/heads/{branch_name}", commit_sha, "")
    if created.returncode != 0:
        return blocked(f"could not create branch {branch_name}: {created.stderr.strip()[:500]}")

    evidence = FileEvidenceStore(artifacts_root)
    apply_ref = evidence.write_json(
        run_id,
        "target",
        {
            "repo_path": str(repo),
            "branch": branch_name,
            "commit": commit_sha,
            "base_commit": base_commit,
            "files": sorted(diff_names),
            "approval": approval,
            "working_tree_touched": False,
        },
        name="apply.json",
    )
    append_operator_event(
        artifacts_root,
        run_id,
        AuditEventType.TARGET_PATCH_APPLIED,
        actor=actor,
        component="fix_repo_apply",
        evidence_refs=(apply_ref,),
        metadata={"branch": branch_name, "commit": commit_sha, "repo_path": str(repo)},
    )

    result = ApplyResult(
        "APPLIED",
        run_id,
        f"Created branch {branch_name} at {commit_sha[:12]}; working tree and current branch untouched.",
        repo_path=str(repo),
        branch=branch_name,
        commit=commit_sha,
    )

    if push or open_pr:
        pushed = git(repo, "push", "--set-upstream", remote, f"refs/heads/{branch_name}:refs/heads/{branch_name}", timeout=300)
        if pushed.returncode != 0:
            result.status = "PARTIAL"
            result.message += f" Push failed: {pushed.stderr.strip()[:500]}"
            result.next_steps = [f"git -C {repo} push --set-upstream {remote} {branch_name}"]
            return result
        result.pushed = True
        append_operator_event(
            artifacts_root, run_id, AuditEventType.TARGET_BRANCH_PUSHED,
            actor=actor, component="fix_repo_apply", metadata={"branch": branch_name, "remote": remote},
        )

    if open_pr:
        gh = shutil.which("gh")
        if gh is None:
            result.status = "PARTIAL"
            result.message += " GitHub CLI (gh) not found; PR not opened."
            result.next_steps = [f"gh pr create --head {branch_name} --fill"]
            return result
        title = _commit_message(metadata, run_id, approval).splitlines()[0]
        body = _commit_message(metadata, run_id, approval)
        pr = subprocess.run(
            [gh, "pr", "create", "--head", branch_name, "--title", title, "--body", body],
            cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=300,
        )
        if pr.returncode != 0:
            result.status = "PARTIAL"
            result.message += f" gh pr create failed: {pr.stderr.strip()[:500]}"
            return result
        result.pr_url = pr.stdout.strip().splitlines()[-1] if pr.stdout.strip() else ""
        append_operator_event(
            artifacts_root, run_id, AuditEventType.TARGET_PR_OPENED,
            actor=actor, component="fix_repo_apply", metadata={"branch": branch_name, "url": result.pr_url},
        )

    if not result.pushed:
        result.next_steps = [f"git -C {repo} switch {branch_name}", f"git -C {repo} push --set-upstream {remote} {branch_name}"]
    return result

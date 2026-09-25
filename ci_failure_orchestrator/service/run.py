"""fix-repo run: reproduce, propose, verify in a worktree, and decide through the foundation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..foundation.models import FailureEvent, RunStatus, new_id
from ..foundation.persistence import FileEvidenceStore
from ..foundation.retry import RetryBudget
from ..foundation.runner import AgentExecutionFoundation
from ..patch_sandbox import WorktreePatchVerifier
from .adapters import RepoFixProposalFactory, WorktreeSandbox
from .common import (
    DEFAULT_ENV_ALLOWLIST,
    FINAL_PATCH_NAME,
    FIX_DIR,
    METADATA_NAME,
    blocked_env_names,
    git,
    split_command,
)
from .ingest import clean_failure, failure_from_reproduction, related_tracked_paths
from .patches import parse_patch_files
from .proposals import PatchFileSource, ProposalSource, ProviderCommandSource
from .session import FixSession, VerifyCommand


@dataclass
class FixRepoConfig:
    repo_path: Path
    verify_commands: Sequence[str]
    patch_file: Path | None = None
    provider_cmd: str | None = None
    provider_env: Sequence[str] = ()
    provider_timeout: int = 600
    verify_env: Sequence[str] = ()
    verify_timeout: int = 600
    base_ref: str = "HEAD"
    max_attempts: int = 3
    artifacts_root: Path = Path("artifacts")
    failure: dict[str, Any] | None = None


def _outcome(**values: Any) -> dict[str, Any]:
    values.setdefault("primary_workspace_mutated", False)
    return values


def _build_commands(raw: Sequence[str]) -> tuple[VerifyCommand, ...]:
    commands = tuple(
        VerifyCommand(name=f"step-{idx}", display=cmd.strip(), argv=split_command(cmd))
        for idx, cmd in enumerate(raw, start=1)
        if cmd.strip()
    )
    if not commands:
        raise ValueError("at least one --verify command is required")
    return commands


def _build_source(config: FixRepoConfig) -> ProposalSource:
    if bool(config.patch_file) == bool(config.provider_cmd):
        raise ValueError("exactly one of --patch-file or --provider-cmd is required")
    if config.patch_file:
        return PatchFileSource(config.patch_file)
    return ProviderCommandSource(
        split_command(str(config.provider_cmd)),
        timeout_seconds=config.provider_timeout,
        env_passthrough=config.provider_env,
    )


def run_fix_repo(config: FixRepoConfig) -> dict[str, Any]:
    repo = Path(config.repo_path).resolve()
    artifacts_root = Path(config.artifacts_root).resolve()
    if not (repo / ".git").exists():
        return _outcome(outcome="ERROR", message=f"not a git repository: {repo}")

    try:
        blocked = blocked_env_names(config.verify_env)
        if blocked:
            raise ValueError(f"refusing to pass credential variables to verification commands: {', '.join(blocked)}")
        commands = _build_commands(config.verify_commands)
        source = _build_source(config)
    except ValueError as exc:
        return _outcome(outcome="ERROR", message=str(exc))

    rev = git(repo, "rev-parse", "--verify", f"{config.base_ref}^{{commit}}")
    if rev.returncode != 0:
        return _outcome(outcome="ERROR", message=f"cannot resolve base ref {config.base_ref!r}: {rev.stderr.strip()}")
    base_commit = rev.stdout.strip()

    verifier = WorktreePatchVerifier(
        commands=[(c.name, c.argv) for c in commands],
        timeout_seconds=config.verify_timeout,
        env_allowlist=DEFAULT_ENV_ALLOWLIST + tuple(config.verify_env),
    )
    baseline = verifier.reproduce(repo_path=repo, base_ref=base_commit)
    if baseline is None:
        return _outcome(outcome="ERROR", message="could not create a disposable worktree at the base commit")
    if baseline and all(step.passed for step in baseline):
        return _outcome(
            outcome="NO_FAILURE",
            repo_path=str(repo),
            base_commit=base_commit,
            message=(
                "All verification commands already pass at the base commit, so no patch can be shown to fix "
                "anything. Use --verify commands that reproduce the CI failure locally."
            ),
        )

    failure = clean_failure(config.failure) if config.failure else failure_from_reproduction(baseline, commands)
    tracked = tuple(
        line for line in git(repo, "ls-tree", "-r", "--name-only", base_commit).stdout.splitlines() if line
    )
    if not failure.get("changed_paths"):
        failure["changed_paths"] = list(
            related_tracked_paths(str(failure.get("log_excerpt") or "") + "\n" + str(failure.get("message") or ""), tracked)
        )

    run_id = new_id("run")
    failure.setdefault("source", "fix-repo")
    failure["commit_sha"] = failure.get("commit_sha") or base_commit
    failure["repository"] = failure.get("repository") or str(repo)
    event = FailureEvent.from_dict(failure, run_id=run_id)

    session = FixSession(
        repo=repo,
        base_commit=base_commit,
        commands=commands,
        failure=failure,
        baseline=baseline,
        tracked_files=tracked,
        artifacts_root=artifacts_root,
    )
    foundation = AgentExecutionFoundation(
        sandbox=WorktreeSandbox(session, verifier),
        proposal_factory=RepoFixProposalFactory(session, source),
        workspace_root=repo,
        artifacts_root=artifacts_root,
        enable_persistence=True,
        retry_budget=RetryBudget(max_attempts=max(1, config.max_attempts)),
    )
    result = foundation.run(event)
    workflow = result.workflow_status or result.status.value
    proposal = result.run.proposal

    patch_path: Path | None = None
    files_changed: tuple[str, ...] = ()
    if result.technical_status == "PASS" and proposal is not None:
        files_changed = parse_patch_files(proposal.patch)
        fix_root = artifacts_root / "runs" / run_id / FIX_DIR
        fix_root.mkdir(parents=True, exist_ok=True)
        patch_path = fix_root / FINAL_PATCH_NAME
        patch_path.write_bytes(proposal.patch.encode("utf-8"))
        FileEvidenceStore(artifacts_root).write_json(
            run_id,
            FIX_DIR,
            {
                "repo_path": str(repo),
                "base_ref": config.base_ref,
                "base_commit": base_commit,
                "patch_sha256": sha256(proposal.patch.encode("utf-8")).hexdigest(),
                "files_changed": list(files_changed),
                "verify_commands": [c.display for c in commands],
                "proposal_id": proposal.proposal_id,
                "proposal_source": source.name,
                "failure_message": str(failure.get("message") or "")[:300],
            },
            name=METADATA_NAME,
        )

    next_steps: list[str] = []
    if workflow == RunStatus.APPROVED.value:
        next_steps.append(f"python -m ci_failure_orchestrator.cli fix-repo-apply {run_id} --artifacts {config.artifacts_root}")
    elif workflow == RunStatus.AWAITING_HUMAN.value:
        next_steps.append(f"Review {patch_path} and the escalation package, then:")
        next_steps.append(
            f"python -m ci_failure_orchestrator.cli foundation-decide {run_id} --action APPROVE "
            f"--reviewer <you> --artifacts {config.artifacts_root}"
        )
        next_steps.append(f"python -m ci_failure_orchestrator.cli fix-repo-apply {run_id} --artifacts {config.artifacts_root}")
    else:
        next_steps.append(f"Inspect artifacts under {artifacts_root / 'runs' / run_id}")

    return _outcome(
        outcome=workflow,
        run_id=run_id,
        workflow_status=workflow,
        technical_status=result.technical_status,
        policy_outcome=result.policy_outcome.value if result.policy_outcome else None,
        policy_rules=list(result.policy_decision.matched_rules) if result.policy_decision else [],
        attempts=result.attempts,
        stop_reason=result.stop_reason.value if result.stop_reason else None,
        repo_path=str(repo),
        base_commit=base_commit,
        files_changed=list(files_changed),
        patch_path=str(patch_path) if patch_path else None,
        feedback=session.feedback,
        artifacts=str(artifacts_root / "runs" / run_id),
        next_steps=next_steps,
    )

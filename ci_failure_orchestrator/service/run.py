"""fix-repo run: reproduce, propose, verify in a worktree, and decide through the foundation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..foundation.models import FailureEvent, RunStatus, new_id, utc_now
from ..foundation.persistence import FileEvidenceStore
from ..foundation.retry import RetryBudget
from ..foundation.runner import AgentExecutionFoundation
from ..patch_sandbox import WorktreePatchVerifier
from .adapters import RepoFixProposalFactory, WorktreeSandbox
from .common import (
    DEFAULT_ENV_ALLOWLIST,
    ESCALATION_NAME,
    FINAL_PATCH_NAME,
    FIX_DIR,
    METADATA_NAME,
    VERIFICATION_NAME,
    blocked_env_names,
    git,
    split_command,
)
from .environment import EnvironmentFinding, detect_environment_failure
from .ingest import clean_failure, failure_from_reproduction, related_tracked_paths
from .patches import parse_patch_files
from .proposals import PatchFileSource, ProposalSource, ProviderCommandSource
from .records import Task, TaskStore
from .session import FixSession, VerifyCommand
from .verification import (
    BLOCKING_REMEDIATION_STATES,
    VerificationConfig,
    collect_verification,
    record_verification,
    static_verification,
)


# Every attempt may call a model provider and run the full verification suite.
MAX_ATTEMPTS_CEILING = 10


@dataclass
class FixRepoConfig:
    """Operator settings for one fix-repo run."""

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
    task_id: str | None = None
    verification: VerificationConfig | None = None


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


def _task_for(tasks: TaskStore, task: Task | None, failure: dict[str, Any], repo: Path) -> Task:
    if task is not None:
        return task
    return tasks.create(
        repository=str(failure.get("repository") or repo),
        trigger=str(failure.get("source") or "fix-repo"),
        objective=str(failure.get("message") or "make the failing verification commands pass")[:300],
    )


def _escalate_environment(
    config: FixRepoConfig,
    finding: EnvironmentFinding,
    *,
    failure: dict[str, Any],
    repo: Path,
    base_commit: str,
    artifacts_root: Path,
    tasks: TaskStore,
    task: Task | None,
    source: ProposalSource,
) -> dict[str, Any]:
    """Escalate before any provider call: the reproduction failed for an environment reason."""
    run_id = new_id("run")
    task = _task_for(tasks, task, failure, repo)
    reason = f"environment_failure:{finding.kind}"
    record = {
        "stage": "reproduce",
        "reason": reason,
        "finding": finding.to_dict(),
        "repo_path": str(repo),
        "base_commit": base_commit,
        "task_id": task.task_id,
        "provider_called": False,
        "failure_message": str(failure.get("message") or "")[:300],
        "created_at": utc_now(),
    }
    ref = FileEvidenceStore(artifacts_root).write_json(run_id, FIX_DIR, record, name=ESCALATION_NAME)
    tasks.append_run(
        task.task_id,
        {
            "run_id": run_id,
            "started_at": record["created_at"],
            "completed_at": utc_now(),
            "workflow_status": RunStatus.AWAITING_HUMAN.value,
            "technical_status": None,
            "policy_outcome": None,
            "risk_level": None,
            "attempts": 0,
            "stop_reason": reason,
            "base_commit": base_commit,
            "proposal_source": source.name,
            "agent": source.agent,
        },
    )
    return _outcome(
        outcome=RunStatus.AWAITING_HUMAN.value,
        run_id=run_id,
        task_id=task.task_id,
        workflow_status=RunStatus.AWAITING_HUMAN.value,
        technical_status=None,
        policy_outcome=None,
        attempts=0,
        stop_reason=reason,
        provider_called=False,
        escalation=record,
        repo_path=str(repo),
        base_commit=base_commit,
        artifacts=str(artifacts_root / "runs" / run_id),
        escalation_path=str(artifacts_root / "runs" / run_id / ref.ref),
        next_steps=[
            f"The unpatched reproduction failed for an environment reason ({finding.kind}): {finding.evidence}",
            "No patch was requested. Fix the environment or the verification command, then re-run:",
            f"python -m ci_failure_orchestrator.cli fix-repo ... --task-id {task.task_id} --artifacts {config.artifacts_root}",
        ],
    )


def run_fix_repo(config: FixRepoConfig) -> dict[str, Any]:
    """Reproduce the failure, propose and verify patches in worktrees, and record the decision.

    Runs that fail to reproduce, or that fail for an environment reason, stop before any
    proposal is requested. Invalid configuration is returned as an ``ERROR`` outcome.
    """
    repo = Path(config.repo_path).resolve()
    artifacts_root = Path(config.artifacts_root).resolve()
    if not (repo / ".git").exists():
        return _outcome(outcome="ERROR", message=f"not a git repository: {repo}")

    try:
        if not 1 <= config.max_attempts <= MAX_ATTEMPTS_CEILING:
            raise ValueError(f"--max-attempts must be between 1 and {MAX_ATTEMPTS_CEILING}, got {config.max_attempts}")
        blocked = blocked_env_names(config.verify_env)
        if blocked:
            raise ValueError(f"refusing to pass credential variables to verification commands: {', '.join(blocked)}")
        commands = _build_commands(config.verify_commands)
        source = _build_source(config)
        tasks = TaskStore(artifacts_root)
        task: Task | None = tasks.load(config.task_id) if config.task_id else None
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
    finding = detect_environment_failure(baseline, commands, tracked)
    if finding is not None:
        return _escalate_environment(
            config, finding, failure=failure, repo=repo, base_commit=base_commit,
            artifacts_root=artifacts_root, tasks=tasks, task=task, source=source,
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
    task = _task_for(tasks, task, failure, repo)
    started_at = utc_now()

    session = FixSession(
        repo=repo,
        base_commit=base_commit,
        commands=commands,
        failure=failure,
        baseline=baseline,
        tracked_files=tracked,
        artifacts_root=artifacts_root,
        task_id=task.task_id,
        proposal_source=source.name,
        agent=source.agent,
    )
    foundation = AgentExecutionFoundation(
        sandbox=WorktreeSandbox(session, verifier),
        proposal_factory=RepoFixProposalFactory(session, source),
        workspace_root=repo,
        artifacts_root=artifacts_root,
        enable_persistence=True,
        retry_budget=RetryBudget(max_attempts=config.max_attempts),
    )
    result = foundation.run(event)
    workflow = result.workflow_status or result.status.value
    proposal = result.run.proposal
    policy_outcome = result.policy_outcome.value if result.policy_outcome else None
    stop_reason = result.stop_reason.value if result.stop_reason else None
    tasks.append_run(
        task.task_id,
        {
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": utc_now(),
            "workflow_status": workflow,
            "technical_status": result.technical_status,
            "policy_outcome": policy_outcome,
            "risk_level": result.policy_decision.risk_level.value if result.policy_decision else None,
            "attempts": result.attempts,
            "stop_reason": stop_reason,
            "base_commit": base_commit,
            "proposal_source": source.name,
            "agent": source.agent,
        },
    )

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
                "agent": source.agent,
                "task_id": task.task_id,
                "failure_message": str(failure.get("message") or "")[:300],
            },
            name=METADATA_NAME,
        )

    technical_passed = result.technical_status == "PASS" and proposal is not None
    policy_risk = result.policy_decision.risk_level.value if result.policy_decision else None
    ci_log = str(failure.get("log_excerpt") or "") if config.failure else None
    common = {
        "baseline": baseline,
        "commands": commands,
        "ci_failure_log": ci_log or None,
        "policy_outcome": policy_outcome,
        "policy_risk": policy_risk,
    }
    if technical_passed and policy_outcome != "REJECT":
        report = collect_verification(
            repo=repo,
            base_commit=base_commit,
            patch=proposal.patch,
            config=config.verification or VerificationConfig(),
            timeout=config.verify_timeout,
            env_allowlist=DEFAULT_ENV_ALLOWLIST + tuple(config.verify_env),
            **common,
        )
    else:
        report = static_verification(
            patch=proposal.patch if proposal is not None else "",
            repair_proposed=proposal is not None,
            technical_passed=technical_passed,
            **common,
        )
    remediation = record_verification(
        artifacts_root,
        run_id,
        report,
        stage="local",
        record_name=VERIFICATION_NAME,
        repair_attempt=result.attempts,
        failure_received_at=started_at,
        ci_green=technical_passed,
        ci_green_source="sandbox",
        extra={"verification_config": (config.verification or VerificationConfig()).to_dict()},
    )
    state = report.decision.state.value

    next_steps: list[str] = []
    if state in BLOCKING_REMEDIATION_STATES:
        next_steps.append(
            f"Repair verification: {state} ({', '.join(report.decision.reasons)}). fix-repo-apply will refuse this run."
        )
        next_steps.append(f"Inspect artifacts under {artifacts_root / 'runs' / run_id}")
    elif workflow == RunStatus.APPROVED.value:
        next_steps.append(
            f"python -m ci_failure_orchestrator.cli fix-repo-apply {run_id} --open-pr --artifacts {config.artifacts_root}"
        )
        next_steps.append(
            f"python -m ci_failure_orchestrator.cli fix-repo-verify-ci {run_id} --repository <owner/name> "
            f"--artifacts {config.artifacts_root}  # VERIFIED_FIXED needs the real CI run to pass"
        )
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
        task_id=task.task_id,
        agent=source.agent,
        workflow_status=workflow,
        technical_status=result.technical_status,
        policy_outcome=policy_outcome,
        policy_rules=list(result.policy_decision.matched_rules) if result.policy_decision else [],
        attempts=result.attempts,
        stop_reason=stop_reason,
        repo_path=str(repo),
        base_commit=base_commit,
        files_changed=list(files_changed),
        patch_path=str(patch_path) if patch_path else None,
        feedback=session.feedback,
        remediation_state=state,
        remediation=remediation,
        artifacts=str(artifacts_root / "runs" / run_id),
        next_steps=next_steps,
    )

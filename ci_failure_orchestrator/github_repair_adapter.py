"""GitHub Actions evidence adapter for the policy-driven repair supervisor.

This module converts normalized workflow/job evidence into a provider-neutral repair
contract. It deliberately does not call GitHub, execute shell commands, mutate git,
or invoke an AI model; those capabilities live behind external workers/connectors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .supervisor import (
    RepairAuthority,
    RepairRequest,
    SupervisorDecision,
    SupervisorPolicy,
    evaluate_repair,
)


@dataclass(frozen=True)
class FailedCheck:
    """Normalized evidence for one failed GitHub Actions job or check."""

    workflow: str
    job: str
    failed_step: str
    log_excerpt: str = ""
    changed_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentTask:
    """Bounded task contract passed to a repair worker."""

    objective: str
    failure_class: str
    authority: RepairAuthority
    allowed_paths: tuple[str, ...]
    required_gates: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class GitHubRepairPlan:
    """Supervisor decision plus optional worker task for one failed check."""

    decision: SupervisorDecision
    task: AgentTask | None
    should_rerun_after_patch: bool


def classify_failed_check(check: FailedCheck) -> str:
    """Map common Actions failures to stable repair classes.

    Classification is intentionally conservative: unknown failures remain unknown
    so the supervisor can fail closed or require review instead of guessing.
    """

    haystack = " ".join(
        (check.workflow, check.job, check.failed_step, check.log_excerpt)
    ).lower()
    if "ruff" in haystack or "flake8" in haystack or "lint" in haystack:
        return "lint"
    if "black" in haystack or "format" in haystack:
        return "formatting"
    if "mypy" in haystack or "pyright" in haystack or "type check" in haystack:
        return "typing"
    if "workflow" in haystack and ("yaml" in haystack or "syntax" in haystack):
        return "workflow_syntax"
    if "pytest" in haystack or "test" in check.failed_step.lower():
        return "unit_test_failure"
    return "unknown"


def build_repair_plan(
    check: FailedCheck,
    *,
    attempt: int = 1,
    cost_spent_usd: float = 0.0,
    elapsed_seconds: int = 0,
    predicted_changed_lines: int = 0,
    policy: SupervisorPolicy | None = None,
) -> GitHubRepairPlan:
    """Create a bounded repair plan from failed GitHub Actions evidence."""

    failure_class = classify_failed_check(check)
    decision = evaluate_repair(
        RepairRequest(
            failure_class=failure_class,
            changed_paths=check.changed_paths,
            predicted_changed_lines=predicted_changed_lines,
            attempt=attempt,
            cost_spent_usd=cost_spent_usd,
            elapsed_seconds=elapsed_seconds,
            unknown_failure=failure_class == "unknown",
        ),
        policy,
    )

    if decision.authority is RepairAuthority.DENY:
        return GitHubRepairPlan(decision, None, False)

    evidence = tuple(
        item
        for item in (
            f"workflow={check.workflow}",
            f"job={check.job}",
            f"failed_step={check.failed_step}",
            f"log_excerpt={check.log_excerpt[:2000]}" if check.log_excerpt else "",
        )
        if item
    )
    objective = (
        "Determine the root cause and propose the smallest safe repair. "
        "Do not weaken tests, checks, security controls, or policy to obtain green CI."
    )
    task = AgentTask(
        objective=objective,
        failure_class=failure_class,
        authority=decision.authority,
        allowed_paths=check.changed_paths,
        required_gates=decision.required_gates,
        forbidden_actions=decision.forbidden_actions,
        evidence=evidence,
    )
    return GitHubRepairPlan(
        decision=decision,
        task=task,
        should_rerun_after_patch=decision.authority
        in {RepairAuthority.AUTONOMOUS_PATCH, RepairAuthority.PATCH_REQUIRES_REVIEW},
    )


def summarize_failed_jobs(jobs: Iterable[dict]) -> tuple[FailedCheck, ...]:
    """Normalize connector/API job dictionaries into failed-check evidence."""

    failed: list[FailedCheck] = []
    for job in jobs:
        if job.get("conclusion") != "failure":
            continue
        failed_step = "unknown"
        for step in job.get("steps", ()):  # GitHub order is execution order.
            if step.get("conclusion") == "failure":
                failed_step = str(step.get("name") or "unknown")
                break
        failed.append(
            FailedCheck(
                workflow=str(job.get("workflow") or job.get("workflow_name") or "unknown"),
                job=str(job.get("name") or "unknown"),
                failed_step=failed_step,
            )
        )
    return tuple(failed)

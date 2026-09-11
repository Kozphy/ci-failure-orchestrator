from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .classifier import classify_error
from .langgraph_runtime import AgentWorkflowState, StateHook, StateUpdate
from .patch_sandbox import WorktreePatchVerifier
from .provider_adapters import ProviderRun, ProviderSpec, SandboxRunner
from .repair_execution import VerificationResultEvaluator, extract_unified_diff
from .repair_planner import RepairPlan
from .telemetry import MetricsRegistry, OpenTelemetryRecorder, Timer


RETRYABLE_FAILURE_CLASSES = frozenset(
    {
        "NETWORK_ERROR",
        "FLAKY_TEST",
        "PACKAGE_ERROR",
        "RUNTIME_ERROR",
    }
)


def classifier_diagnose_hook(state: AgentWorkflowState) -> StateUpdate:
    message = state.get("failure_message", "")
    failure_class, confidence = classify_error(message)
    return {
        "failure_class": failure_class,
        "confidence": confidence,
        "retryable": failure_class in RETRYABLE_FAILURE_CLASSES,
        "diagnosis": f"deterministic classifier selected {failure_class}",
    }


def repair_plan_to_state(plan: RepairPlan) -> StateUpdate:
    """Serialize the deterministic repair plan into bounded workflow state."""

    return {
        "repair_plan": plan.to_dict(),
        "repair_risk": plan.risk,
        "repair_requires_human_approval": plan.requires_human_approval,
    }


def repair_plan_prompt(plan: RepairPlan, state: AgentWorkflowState) -> str:
    """Build the provider prompt from the deterministic RepairPlan contract."""

    targets = ", ".join(plan.target_files) if plan.target_files else "not specified"
    verification = ", ".join(step.name for step in plan.verification) or "repository verification suite"
    return (
        "Produce exactly one minimal reversible git unified diff for this repair plan.\n"
        "Do not weaken tests, security policy, or verification commands.\n"
        "Do not include credentials, secrets, unrelated refactors, or prose outside the diff.\n"
        f"Root stage: {plan.root_stage}\n"
        f"Hypothesis: {plan.hypothesis}\n"
        f"Proposed change: {plan.proposed_change}\n"
        f"Target files: {targets}\n"
        f"Risk: {plan.risk}\n"
        f"Required verification: {verification}\n"
        f"Failure message: {state.get('failure_message', '')}\n"
    )


def repair_plan_prompt_builder(plan: RepairPlan) -> Callable[[AgentWorkflowState], str]:
    return lambda state: repair_plan_prompt(plan, state)


def default_repair_prompt(state: AgentWorkflowState) -> str:
    return (
        "Produce the smallest reversible git unified diff that addresses this CI failure.\n"
        "Do not include secrets, credentials, or unrelated refactors.\n"
        f"Failure class: {state.get('failure_class', 'UNKNOWN')}\n"
        f"Diagnosis: {state.get('diagnosis', '')}\n"
        f"Failure message: {state.get('failure_message', '')}\n"
    )


def provider_patch_hook(
    runner: SandboxRunner,
    spec: ProviderSpec,
    *,
    prompt_builder: Callable[[AgentWorkflowState], str] = default_repair_prompt,
) -> StateHook:
    def hook(state: AgentWorkflowState) -> StateUpdate:
        run = runner.run(
            spec,
            prompt=prompt_builder(state),
            repo_path=state.get("repo_path"),
        )
        patch = extract_unified_diff(run.stdout)
        return {
            "patch": patch,
            "provider": run.provider,
            "provider_returncode": run.returncode,
            "provider_stdout": run.stdout,
            "provider_stderr": run.stderr,
            "provider_latency_ms": run.latency_ms,
            "provider_command": list(run.command),
        }

    return hook


def worktree_sandbox_hook(
    verifier: WorktreePatchVerifier,
    *,
    base_ref: str = "HEAD",
) -> StateHook:
    evaluator = VerificationResultEvaluator()

    def hook(state: AgentWorkflowState) -> StateUpdate:
        repo_path = state.get("repo_path")
        if not repo_path:
            return {
                "sandbox_passed": False,
                "verification_score": 0.0,
                "regression_free": False,
                "reason": "repo_path is required for sandbox verification",
            }

        provider_run = ProviderRun(
            provider=str(state.get("provider", "unknown")),
            returncode=int(state.get("provider_returncode", 1)),
            stdout=str(state.get("provider_stdout", state.get("patch", ""))),
            stderr=str(state.get("provider_stderr", "")),
            latency_ms=float(state.get("provider_latency_ms", 0.0)),
            command=tuple(str(item) for item in state.get("provider_command", ())),
            sandbox="langgraph-provider",
        )
        patch = str(state.get("patch", ""))
        verification = None
        if provider_run.returncode == 0 and patch:
            verification = verifier.verify(
                repo_path=repo_path,
                patch_text=patch,
                base_ref=base_ref,
            )

        evaluation = evaluator.evaluate(verification, provider_run)
        return {
            "sandbox_passed": bool(verification and verification.passed),
            "verification_score": evaluation.score,
            "regression_free": evaluation.regression_free,
            "verification_reasons": list(evaluation.reasons),
            "changed_files": list(verification.changed_files) if verification else [],
            "patch_sha256": verification.patch_sha256 if verification else None,
            "sandbox_latency_ms": verification.total_latency_ms if verification else 0.0,
        }

    return hook


def verification_passthrough_hook(state: AgentWorkflowState) -> StateUpdate:
    return {
        "verification_score": float(state.get("verification_score", 0.0)),
        "regression_free": bool(state.get("regression_free", False)),
    }


def draft_pr_gate_hook(
    state: AgentWorkflowState,
    *,
    minimum_score: float = 0.90,
) -> StateUpdate:
    reasons: list[str] = []
    if not bool(state.get("sandbox_passed", False)):
        reasons.append("sandbox_not_passed")
    if not bool(state.get("regression_free", False)):
        reasons.append("regression_detected")
    if float(state.get("verification_score", 0.0)) < minimum_score:
        reasons.append("verification_score_below_threshold")
    if bool(state.get("dead_lettered", False)):
        reasons.append("dead_lettered")
    if bool(state.get("repair_requires_human_approval", False)) and not bool(
        state.get("human_approved", False)
    ):
        reasons.append("repair_plan_requires_human_approval")

    allowed = not reasons
    return {
        "draft_pr_allowed": allowed,
        "delivery_gate_reasons": reasons,
    }


def instrument_hook(
    name: str,
    hook: StateHook,
    registry: MetricsRegistry,
) -> StateHook:
    metric = f"langgraph.node.{name}.latency_ms"

    def wrapped(state: AgentWorkflowState) -> StateUpdate:
        registry.inc(f"langgraph.node.{name}.runs")
        with Timer(registry, metric):
            try:
                update = hook(state)
            except Exception:
                registry.inc(f"langgraph.node.{name}.errors")
                raise
        registry.inc(f"langgraph.node.{name}.success")
        return update

    return wrapped


def otel_instrument_hook(
    name: str,
    hook: StateHook,
    recorder: OpenTelemetryRecorder,
) -> StateHook:
    """Wrap one node in an OpenTelemetry span without exporting raw state payloads."""

    def wrapped(state: AgentWorkflowState) -> StateUpdate:
        with recorder.node_span(
            name,
            run_id=str(state.get("run_id", "")),
            repository=str(state.get("repository", "")),
            failure_class=str(state.get("failure_class", "")),
        ):
            return hook(state)

    return wrapped


@dataclass
class InMemoryDeadLetterSink:
    records: list[dict[str, Any]] = field(default_factory=list)

    def hook(self, state: AgentWorkflowState) -> StateUpdate:
        record = _dead_letter_record(state)
        self.records.append(record)
        return {"dead_letter_reason": str(record["reason"] or "dead-lettered")}


def _dead_letter_record(state: AgentWorkflowState) -> dict[str, Any]:
    return {
        "run_id": state.get("run_id"),
        "repository": state.get("repository"),
        "failure_class": state.get("failure_class"),
        "retry_count": int(state.get("retry_count", 0)),
        "ai_calls": int(state.get("ai_calls", 0)),
        "ai_cost_usd": float(state.get("ai_cost_usd", 0.0)),
        "reason": state.get("dead_letter_reason") or state.get("reason"),
    }


@dataclass(frozen=True)
class JsonlDeadLetterSink:
    path: str | Path

    def hook(self, state: AgentWorkflowState) -> StateUpdate:
        target = Path(self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        record = _dead_letter_record(state)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return {"dead_letter_reason": str(record["reason"] or "dead-lettered")}


def budgeted_ai_hook(
    hook: StateHook,
    *,
    estimated_cost_usd: float,
    calls: int = 1,
) -> StateHook:
    if calls < 0 or estimated_cost_usd < 0:
        raise ValueError("AI usage estimates must be non-negative")

    def wrapped(state: AgentWorkflowState) -> StateUpdate:
        update = dict(hook(state))
        update["ai_calls_delta"] = calls
        update["ai_cost_usd_delta"] = estimated_cost_usd
        return update

    return wrapped


def compose_hooks(*hooks: Callable[[AgentWorkflowState], StateUpdate]) -> StateHook:
    def composed(state: AgentWorkflowState) -> StateUpdate:
        current: dict[str, Any] = dict(state)
        merged: StateUpdate = {}
        for hook in hooks:
            update = hook(current)
            merged.update(update)
            current.update(update)
        return merged

    return composed

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
from .telemetry import MetricsRegistry, Timer


RETRYABLE_FAILURE_CLASSES = frozenset(
    {
        "NETWORK_ERROR",
        "FLAKY_TEST",
        "PACKAGE_ERROR",
        "RUNTIME_ERROR",
    }
)


def classifier_diagnose_hook(state: AgentWorkflowState) -> StateUpdate:
    """Adapt the repository's existing deterministic classifier to LangGraph state."""

    message = state.get("failure_message", "")
    failure_class, confidence = classify_error(message)
    return {
        "failure_class": failure_class,
        "confidence": confidence,
        "retryable": failure_class in RETRYABLE_FAILURE_CLASSES,
        "diagnosis": f"deterministic classifier selected {failure_class}",
    }


def default_repair_prompt(state: AgentWorkflowState) -> str:
    """Build a bounded provider prompt from serializable workflow state."""

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
    """Run a configured coding provider and persist only serializable evidence in state."""

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
    """Apply and test the candidate patch inside the existing disposable git worktree."""

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
    """Expose deterministic sandbox evaluation to the graph's independent verify node."""

    return {
        "verification_score": float(state.get("verification_score", 0.0)),
        "regression_free": bool(state.get("regression_free", False)),
    }


def draft_pr_gate_hook(
    state: AgentWorkflowState,
    *,
    minimum_score: float = 0.90,
) -> StateUpdate:
    """Fail-closed delivery gate. This authorizes a Draft PR; it never creates one."""

    reasons: list[str] = []
    if not bool(state.get("sandbox_passed", False)):
        reasons.append("sandbox_not_passed")
    if not bool(state.get("regression_free", False)):
        reasons.append("regression_detected")
    if float(state.get("verification_score", 0.0)) < minimum_score:
        reasons.append("verification_score_below_threshold")
    if bool(state.get("dead_lettered", False)):
        reasons.append("dead_lettered")

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
    """Wrap a graph hook with the repository's dependency-free telemetry registry."""

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


@dataclass
class InMemoryDeadLetterSink:
    """Test/local dead-letter sink; production callers can inject a durable sink hook."""

    records: list[dict[str, Any]] = field(default_factory=list)

    def hook(self, state: AgentWorkflowState) -> StateUpdate:
        record = _dead_letter_record(state)
        self.records.append(record)
        return {"dead_letter_reason": str(record["reason"] or "dead-lettered")}


def _dead_letter_record(state: AgentWorkflowState) -> dict[str, Any]:
    """Return the intentionally small, non-secret DLQ payload."""

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
    """Append-only local durable DLQ suitable for a single-host runner.

    It deliberately stores only bounded metadata, not raw logs, prompts, patches, or
    credentials. Multi-host production deployments should replace this with a real
    durable queue or database implementation.
    """

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
    """Annotate an AI-backed hook with usage deltas consumed by the graph runtime.

    The wrapper intentionally does not enforce the budget itself. Enforcement lives in
    the orchestration layer so all AI providers share one durable budget ledger.
    """

    if calls < 0 or estimated_cost_usd < 0:
        raise ValueError("AI usage estimates must be non-negative")

    def wrapped(state: AgentWorkflowState) -> StateUpdate:
        update = dict(hook(state))
        update["ai_calls_delta"] = calls
        update["ai_cost_usd_delta"] = estimated_cost_usd
        return update

    return wrapped


def compose_hooks(*hooks: Callable[[AgentWorkflowState], StateUpdate]) -> StateHook:
    """Compose small state hooks without hiding later updates behind framework magic."""

    def composed(state: AgentWorkflowState) -> StateUpdate:
        current: dict[str, Any] = dict(state)
        merged: StateUpdate = {}
        for hook in hooks:
            update = hook(current)
            merged.update(update)
            current.update(update)
        return merged

    return composed

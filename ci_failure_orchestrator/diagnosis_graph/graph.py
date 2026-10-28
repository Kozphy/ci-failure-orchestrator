"""LangGraph CI diagnosis flow: classify → hypothesize → verify → emit.

Why LangGraph (and not only the existing foundation runner):
- Explicit ``StateGraph`` edges make the diagnosis control flow reviewable.
- ``MemorySaver`` checkpoints by ``thread_id`` so a resumed run can skip a
  consequential emit that already completed.
- ``RetryPolicy`` bounds transient provider failures without retrying timeouts
  or hard errors.

LangGraph node timeouts are async-only in current docs; the hypothesize node
uses a thread-pool wall-clock timeout for the sync mock path.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from ..foundation.classifier import FailureClassifier
from ..foundation.models import FailureEvent
from ..server.logs import log_event
from .providers import (
    HypothesisProvider,
    MockHypothesisProvider,
    ProviderHardError,
    ProviderTransientError,
)

logger = logging.getLogger("ci_failure_orchestrator.diagnosis_graph")


class DiagnosisState(TypedDict, total=False):
    """Graph state. Model fields stay separate from verification fields."""

    run_id: str
    message: str
    log_excerpt: str
    workflow: str
    job: str
    failed_step: str
    # Deterministic classifier output
    category: str
    classifier_confidence: float
    classifier_evidence: list[str]
    # Model / mock hypothesis (never the final decision by itself)
    hypothesis_category: str
    hypothesis_text: str
    provider_name: str
    provider_attempts: int
    provider_error: str
    timed_out: bool
    # Deterministic verification
    verification: Literal["MATCH", "MISMATCH", "SKIPPED"]
    decision: str
    # Consequential action ledger inside the graph state
    action_emitted: bool
    consequential_action_id: str


def _retry_transient(exc: BaseException) -> bool:
    return isinstance(exc, ProviderTransientError)


def build_diagnosis_graph(
    *,
    provider: HypothesisProvider | None = None,
    hypothesize_timeout_seconds: float = 2.0,
    max_provider_attempts: int = 3,
    checkpointer: MemorySaver | None = None,
    on_action: Any | None = None,
):
    """Compile the diagnosis graph.

    Args:
        provider: Hypothesis source. Defaults to ``MockHypothesisProvider``.
        hypothesize_timeout_seconds: Wall-clock limit for one hypothesize attempt.
        max_provider_attempts: LangGraph ``RetryPolicy.max_attempts`` for transient errors.
        checkpointer: Defaults to an in-memory saver keyed by ``thread_id``.
        on_action: Optional callback ``(action_id, state) -> None`` invoked at most once
            per ``thread_id`` when a diagnosis decision is emitted.
    """
    provider = provider or MockHypothesisProvider()
    checkpointer = checkpointer or MemorySaver()
    classifier = FailureClassifier()
    # Process-local ledger so a resumed or re-invoked thread cannot emit twice even if
    # new input resets ``action_emitted`` in the graph state.
    emitted_actions: set[str] = set()

    def classify(state: DiagnosisState) -> dict[str, Any]:
        event = FailureEvent.from_dict(
            {
                "run_id": state["run_id"],
                "workflow": state.get("workflow") or "ci",
                "job": state.get("job") or "test",
                "failed_step": state.get("failed_step") or "unknown",
                "message": state.get("message") or "",
                "log_excerpt": state.get("log_excerpt") or "",
            },
            run_id=state["run_id"],
        )
        result = classifier.classify(event)
        log_event(
            logger,
            "diagnosis_classified",
            run_id=state["run_id"],
            category=result.category,
            confidence=result.confidence,
        )
        return {
            "category": result.category,
            "classifier_confidence": result.confidence,
            "classifier_evidence": list(result.evidence),
            "provider_attempts": 0,
            "timed_out": False,
            "provider_error": "",
            "action_emitted": bool(state.get("action_emitted")),
            "consequential_action_id": state.get("consequential_action_id") or "",
        }

    def hypothesize(state: DiagnosisState) -> dict[str, Any]:
        # RetryPolicy re-enters without committing prior writes, so count calls on the provider.
        attempts = int(getattr(provider, "calls", 0)) + 1
        log_event(
            logger,
            "diagnosis_hypothesize_start",
            run_id=state["run_id"],
            provider=provider.name,
            attempt=attempts,
            timeout_seconds=hypothesize_timeout_seconds,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                provider.hypothesize,
                message=state.get("message") or "",
                log_excerpt=state.get("log_excerpt") or "",
                workflow=state.get("workflow") or "ci",
                job=state.get("job") or "test",
                failed_step=state.get("failed_step") or "unknown",
            )
            try:
                category, rationale = future.result(timeout=hypothesize_timeout_seconds)
            except FuturesTimeoutError:
                log_event(
                    logger,
                    "diagnosis_hypothesize_timeout",
                    level=logging.WARNING,
                    run_id=state["run_id"],
                    attempt=attempts,
                )
                return {
                    "provider_attempts": getattr(provider, "calls", attempts),
                    "provider_name": provider.name,
                    "timed_out": True,
                    "provider_error": f"TimeoutError: hypothesize exceeded {hypothesize_timeout_seconds}s",
                    "hypothesis_category": "",
                    "hypothesis_text": "",
                }
            except ProviderTransientError:
                # Let RetryPolicy see the exception so it can retry.
                raise
            except ProviderHardError as exc:
                log_event(
                    logger,
                    "diagnosis_hypothesize_hard_fail",
                    level=logging.WARNING,
                    run_id=state["run_id"],
                    error_type=type(exc).__name__,
                )
                return {
                    "provider_attempts": getattr(provider, "calls", attempts),
                    "provider_name": provider.name,
                    "timed_out": False,
                    "provider_error": f"{type(exc).__name__}: {exc}",
                    "hypothesis_category": "",
                    "hypothesis_text": "",
                }
        log_event(
            logger,
            "diagnosis_hypothesize_ok",
            run_id=state["run_id"],
            provider=provider.name,
            attempt=getattr(provider, "calls", attempts),
            hypothesis_category=category,
        )
        return {
            "provider_attempts": getattr(provider, "calls", attempts),
            "provider_name": provider.name,
            "timed_out": False,
            "provider_error": "",
            "hypothesis_category": category,
            "hypothesis_text": rationale,
        }

    def verify(state: DiagnosisState) -> dict[str, Any]:
        if state.get("timed_out"):
            decision = "DIAGNOSIS_TIMED_OUT"
            verification: Literal["MATCH", "MISMATCH", "SKIPPED"] = "SKIPPED"
        elif state.get("provider_error") or not state.get("hypothesis_category"):
            decision = "DIAGNOSIS_PROVIDER_FAILED"
            verification = "SKIPPED"
        elif state.get("hypothesis_category") == state.get("category"):
            decision = "DIAGNOSIS_CONFIRMED"
            verification = "MATCH"
        else:
            # Model disagreed with the deterministic classifier → escalate, do not trust the model.
            decision = "DIAGNOSIS_ESCALATED"
            verification = "MISMATCH"
        log_event(
            logger,
            "diagnosis_verified",
            run_id=state["run_id"],
            verification=verification,
            decision=decision,
            category=state.get("category"),
            hypothesis_category=state.get("hypothesis_category") or "",
        )
        return {"verification": verification, "decision": decision}

    def emit_decision(state: DiagnosisState) -> dict[str, Any]:
        """Consequential emit: at most once per run_id. Resume or re-invoke must be a no-op."""
        action_id = f"diagnosis-decision:{state['run_id']}"
        if action_id in emitted_actions or (
            state.get("action_emitted") and state.get("consequential_action_id")
        ):
            log_event(
                logger,
                "diagnosis_action_skipped_duplicate",
                run_id=state["run_id"],
                action_id=action_id,
            )
            return {
                "action_emitted": True,
                "consequential_action_id": state.get("consequential_action_id") or action_id,
            }
        emitted_actions.add(action_id)
        if on_action is not None:
            on_action(action_id, dict(state))
        log_event(
            logger,
            "diagnosis_action_emitted",
            run_id=state["run_id"],
            action_id=action_id,
            decision=state.get("decision"),
        )
        return {"action_emitted": True, "consequential_action_id": action_id}

    builder = StateGraph(DiagnosisState)
    builder.add_node("classify", classify)
    builder.add_node(
        "hypothesize",
        hypothesize,
        retry_policy=RetryPolicy(
            max_attempts=max_provider_attempts,
            initial_interval=0.01,
            backoff_factor=1.0,
            max_interval=0.05,
            jitter=False,
            retry_on=_retry_transient,
        ),
    )
    builder.add_node("verify", verify)
    builder.add_node("emit_decision", emit_decision)
    builder.add_edge(START, "classify")
    builder.add_edge("classify", "hypothesize")
    builder.add_edge("hypothesize", "verify")
    builder.add_edge("verify", "emit_decision")
    builder.add_edge("emit_decision", END)
    return builder.compile(checkpointer=checkpointer)


def initial_state(event: FailureEvent) -> DiagnosisState:
    """Map a foundation ``FailureEvent`` into graph input."""
    return {
        "run_id": event.run_id,
        "message": event.message,
        "log_excerpt": event.log_excerpt,
        "workflow": event.workflow,
        "job": event.job,
        "failed_step": event.failed_step,
        "action_emitted": False,
        "consequential_action_id": "",
        "timed_out": False,
        "provider_attempts": 0,
    }

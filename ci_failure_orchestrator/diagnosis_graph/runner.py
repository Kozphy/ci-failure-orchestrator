"""Run the diagnosis graph and persist evidence through existing stores."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from ..foundation.models import FailureClassification, FailureEvent, RunState, RunStatus, utc_now
from ..foundation.persistence import RunPersistence
from ..foundation.results import FoundationResult
from ..server.logs import log_event
from .graph import build_diagnosis_graph, initial_state
from .providers import HypothesisProvider, MockHypothesisProvider

logger = logging.getLogger("ci_failure_orchestrator.diagnosis_graph.runner")

_DECISION_STATUS = {
    "DIAGNOSIS_CONFIRMED": RunStatus.SUCCEEDED,
    "DIAGNOSIS_ESCALATED": RunStatus.AWAITING_HUMAN,
    "DIAGNOSIS_PROVIDER_FAILED": RunStatus.FAILED,
    "DIAGNOSIS_TIMED_OUT": RunStatus.FAILED,
}


class DiagnosisGraphRunner:
    """Worker-compatible runner: ``.run(event) -> FoundationResult``.

    Reuses ``RunPersistence`` for durable state and evidence. The LangGraph
    checkpointer is process-local (``MemorySaver``) and keyed by ``run_id``.
    """

    def __init__(
        self,
        artifacts_root: Path,
        *,
        persistence: RunPersistence | None = None,
        provider: HypothesisProvider | None = None,
        hypothesize_timeout_seconds: float = 2.0,
        max_provider_attempts: int = 3,
        checkpointer: MemorySaver | None = None,
    ) -> None:
        self.artifacts_root = Path(artifacts_root)
        self.persistence = persistence
        self.provider = provider or MockHypothesisProvider()
        self.hypothesize_timeout_seconds = hypothesize_timeout_seconds
        self.max_provider_attempts = max_provider_attempts
        self.checkpointer = checkpointer or MemorySaver()
        self.action_ledger: list[str] = []
        self._graph = build_diagnosis_graph(
            provider=self.provider,
            hypothesize_timeout_seconds=hypothesize_timeout_seconds,
            max_provider_attempts=max_provider_attempts,
            checkpointer=self.checkpointer,
            on_action=self._record_action,
        )

    def _record_action(self, action_id: str, state: dict[str, Any]) -> None:
        if action_id in self.action_ledger:
            return
        self.action_ledger.append(action_id)
        journal = self.persistence
        if journal is None:
            return
        payload = {
            "schema": "diagnosis_graph.decision.v1",
            "action_id": action_id,
            "decision": state.get("decision"),
            "verification": state.get("verification"),
            "category": state.get("category"),
            "hypothesis_category": state.get("hypothesis_category"),
            "hypothesis_text": state.get("hypothesis_text"),
            "provider_name": state.get("provider_name"),
            "provider_attempts": state.get("provider_attempts"),
            "timed_out": state.get("timed_out"),
            "provider_error": state.get("provider_error") or "",
            "note": "hypothesis is model/mock output; decision follows deterministic verification",
        }
        ref = journal.write_json("diagnosis", payload, name="decision.json")
        journal.checkpoint(
            workflow_status=str(state.get("decision") or "DIAGNOSIS_UNKNOWN"),
            technical_status="PASS" if state.get("verification") == "MATCH" else "FAIL",
            stop_reason=str(state.get("decision") or ""),
            latest_evaluation_ref=ref.ref,
        )

    def run(self, event: FailureEvent) -> FoundationResult:
        """Execute the diagnosis graph for one failure event."""
        run_id = event.run_id
        journal = self.persistence
        if journal is not None:
            journal.start_run(run_id, RunStatus.RECEIVED.value)
            ref = journal.write_json("input", event.to_dict(), name="failure-event.json")
            journal.checkpoint(failure_event_ref=ref.ref)

        config = {"configurable": {"thread_id": run_id}}
        log_event(logger, "diagnosis_graph_start", run_id=run_id, provider=self.provider.name)
        final = self._graph.invoke(initial_state(event), config)
        # Resume from the same thread after a completed run: must not emit a second action.
        try:
            resumed = self._graph.invoke(None, config)
        except Exception as exc:  # noqa: BLE001 - resume is best-effort; first result still stands
            log_event(
                logger,
                "diagnosis_graph_resume_skipped",
                level=logging.INFO,
                run_id=run_id,
                error_type=type(exc).__name__,
            )
        else:
            if resumed.get("consequential_action_id"):
                final = resumed

        decision = str(final.get("decision") or "DIAGNOSIS_PROVIDER_FAILED")
        status = _DECISION_STATUS.get(decision, RunStatus.FAILED)
        classification = None
        if final.get("category"):
            classification = FailureClassification(
                run_id=run_id,
                category=str(final["category"]),
                evidence=tuple(final.get("classifier_evidence") or ()),
                confidence=float(final.get("classifier_confidence") or 0.0),
                uncertainty="heuristic",
            )
        state = RunState(
            run_id=run_id,
            status=status,
            event=event,
            classification=classification,
            stop_reason=decision,
            technical_status="PASS" if final.get("verification") == "MATCH" else "FAIL",
            workflow_status=decision,
            artifact_refs={"consequential_action_id": str(final.get("consequential_action_id") or "")},
            updated_at=utc_now(),
        )
        if journal is not None:
            journal.checkpoint(
                workflow_status=decision,
                technical_status=state.technical_status,
                stop_reason=decision,
                current_attempt=int(final.get("provider_attempts") or 0),
            )
        log_event(
            logger,
            "diagnosis_graph_finished",
            run_id=run_id,
            decision=decision,
            actions=len(self.action_ledger),
            provider_attempts=final.get("provider_attempts"),
        )
        return FoundationResult(
            run=state,
            status=status,
            attempts=int(final.get("provider_attempts") or 0),
            technical_status=state.technical_status or "FAIL",
            workflow_status=decision,
            artifact_refs=dict(state.artifact_refs),
        )

    def resume(self, run_id: str) -> dict[str, Any]:
        """Resume from the latest checkpoint without re-supplying input."""
        config = {"configurable": {"thread_id": run_id}}
        return self._graph.invoke(None, config)

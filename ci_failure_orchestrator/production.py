from __future__ import annotations

"""Production execution components for CI repair platform.

This module provides the execution boundary components for production
operations: evaluation adapters and tamper-evident evidence sinks.
It enforces the separation of duties principle that repair agents
propose changes but cannot approve their own release.

Module responsibility:
    - Provide deterministic evaluation signal adapters
    - Implement append-only, hash-chained evidence sinks
    - Support in-memory evidence collection for testing

Key invariants:
    - RegressionAwareEvaluator is provider-neutral
    - HashChainedEvidenceSink writes append-only JSONL with hash chain
    - InMemoryEvidenceSink captures events without persistence

Safety boundaries:
    - HashChainedEvidenceSink creates parent directories automatically
    - Evidence sink records are immutable once written
    - No direct system state mutation beyond evidence recording

Audit Notes:
    - Hash chain provides tamper-evidence for all recorded events
    - Each record contains: timestamp, event, payload, previous_hash, hash
    - GENESIS is used as the initial previous_hash for new sinks
"""

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import time

from .control_plane import Evaluation, RepairProposal
from .models import Failure


class RegressionAwareEvaluator:
    """Adapter for deterministic verification signals.

    Callers inject test/regression signals from CI. This keeps the evaluator
    provider-neutral and makes its policy behavior reproducible in tests.

    Responsibility:
        - Adapt external CI test/regression signals into Evaluation objects
        - Provide consistent, deterministic evaluation results

    Invariants:
        - Evaluation result depends only on injected signals, not on proposal or failure
        - reasons tuple is empty when both tests_passed and regression_free are True

    Usage:
        evaluator = RegressionAwareEvaluator(
            tests_passed=True,
            regression_free=True,
            score=0.95,
        )
        evaluation = evaluator.evaluate(proposal, failure)

    Side effects:
        None. evaluate() returns a new Evaluation each time.

    Audit Notes:
        - Injected signals should come from independent CI verification
        - Evaluation reasons are machine-readable for downstream processing
        - Score is passed through from the injected signal
    """

    def __init__(self, *, tests_passed: bool = True, regression_free: bool = True, score: float = 0.95) -> None:
        """Initialize with verification signals.

        Args:
            tests_passed: Whether verification tests passed
            regression_free: Whether the repair introduced no regressions
            score: Evaluation score to assign (0.0-1.0)
        """
        self.tests_passed = tests_passed
        self.regression_free = regression_free
        self.score = score

    def evaluate(self, proposal: RepairProposal, failure: Failure) -> Evaluation:
        """Evaluate a repair proposal against injected signals.

        Args:
            proposal: RepairProposal to evaluate (currently unused, for API compatibility)
            failure: Failure being addressed (currently unused, for API compatibility)

        Returns:
            Evaluation with pass/fail, regression status, score, and reasons

        Side effects:
            None.

        Audit Notes:
            - Currently ignores proposal and failure (adapter pattern)
            - Real implementation would inspect proposal against failure
        """
        reasons: list[str] = []
        if not self.tests_passed:
            reasons.append("verification_tests_failed")
        if not self.regression_free:
            reasons.append("regression_detected")
        return Evaluation(
            passed=self.tests_passed,
            regression_free=self.regression_free,
            score=self.score,
            reasons=tuple(reasons),
        )


class HashChainedEvidenceSink:
    """Append-only JSONL evidence sink with tamper-evident hash chain.

    Writes evidence records to a JSONL file where each record contains
    a hash of its canonical representation plus the hash of the previous
    record. This creates a hash chain that makes tampering detectable.

    Responsibility:
        - Write append-only evidence records
        - Maintain hash chain for tamper detection
        - Auto-create parent directories

    Invariants:
        - Records are appended, never modified or deleted
        - Each record's hash depends on its content and the previous record's hash
        - File is created if it doesn't exist

    Usage:
        sink = HashChainedEvidenceSink("/path/to/evidence.jsonl")
        sink.record("repair_proposed", {"agent": "v1", "case_id": "abc123"})
        sink.record("repair_accepted", {"score": 0.95})

    Side effects:
        - Creates parent directories if they don't exist
        - Appends records to the file
        - Updates internal previous_hash state

    Audit Notes:
        - Hash chain integrity can be verified by re-reading the file
        - Canonical JSON uses sorted keys and compact separators
        - timestamp is recorded as Unix epoch (time.time())
    """

    def __init__(self, path: str | Path) -> None:
        """Initialize with evidence file path.

        Args:
            path: Path to the evidence JSONL file

        Side effects:
            Creates parent directories if they don't exist.
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.previous_hash = "GENESIS"

    def record(self, event: str, payload: dict[str, object]) -> None:
        """Write an evidence record with hash chain.

        Args:
            event: Event type/name (e.g., "repair_proposed", "evaluation_complete")
            payload: Arbitrary dict containing event-specific data

        Side effects:
            Appends a new record to the evidence file
            Updates internal previous_hash for next record

        Audit Notes:
            - Each record contains: timestamp, event, payload, previous_hash, hash
            - Hash is computed from canonical JSON (sorted keys, compact separators)
        """
        body = {
            "timestamp": time(),
            "event": event,
            "payload": payload,
            "previous_hash": self.previous_hash,
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        digest = sha256(canonical.encode("utf-8")).hexdigest()
        record = {**body, "hash": digest}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        self.previous_hash = digest


class InMemoryEvidenceSink:
    """In-memory evidence sink for testing and ephemeral collection.

    Captures evidence events in a list without persistence. Useful for
    unit tests and scenarios where file system access is not desired.

    Responsibility:
        - Collect evidence events in memory
        - Provide same interface as HashChainedEvidenceSink

    Invariants:
        - Events are appended to the list in order
        - No hash chain or tamper-evidence (for testing only)

    Usage:
        sink = InMemoryEvidenceSink()
        sink.record("test_event", {"data": "value"})
        assert len(sink.events) == 1

    Side effects:
        Appends to internal events list.

    Audit Notes:
        - Not suitable for production use (no persistence, no tamper-evidence)
        - Use only for testing or ephemeral scenarios
    """

    def __init__(self) -> None:
        """Initialize with empty events list."""
        self.events: list[dict[str, object]] = []

    def record(self, event: str, payload: dict[str, object]) -> None:
        """Capture an evidence event.

        Args:
            event: Event type/name
            payload: Event-specific data

        Side effects:
            Appends to internal events list.
        """
        self.events.append({"event": event, "payload": payload})

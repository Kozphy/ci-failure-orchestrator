from __future__ import annotations

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
    """

    def __init__(self, *, tests_passed: bool = True, regression_free: bool = True, score: float = 0.95) -> None:
        self.tests_passed = tests_passed
        self.regression_free = regression_free
        self.score = score

    def evaluate(self, proposal: RepairProposal, failure: Failure) -> Evaluation:
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
    """Append-only JSONL evidence with a simple tamper-evident hash chain."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.previous_hash = "GENESIS"

    def record(self, event: str, payload: dict[str, object]) -> None:
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
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, event: str, payload: dict[str, object]) -> None:
        self.events.append({"event": event, "payload": payload})

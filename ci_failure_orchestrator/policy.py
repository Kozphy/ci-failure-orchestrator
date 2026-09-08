from __future__ import annotations

from .control_plane import Decision, Evaluation, RunState


class DefaultRepairPolicy:
    """Fail-closed release policy for autonomous repair."""

    def __init__(self, *, release_score: float = 0.90, retry_score: float = 0.60) -> None:
        self.release_score = release_score
        self.retry_score = retry_score

    def decide(self, evaluation: Evaluation, state: RunState) -> Decision:
        if not evaluation.regression_free:
            return Decision.BLOCK
        if evaluation.passed and evaluation.score >= self.release_score:
            return Decision.RELEASE
        if evaluation.score >= self.retry_score:
            return Decision.RETRY
        return Decision.ESCALATE

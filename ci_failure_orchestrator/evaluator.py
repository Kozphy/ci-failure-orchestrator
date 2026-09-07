from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetryBudget:
    max_attempts: int = 3
    attempts: int = 0

    def consume(self) -> bool:
        if self.attempts >= self.max_attempts:
            return False
        self.attempts += 1
        return True

    @property
    def exhausted(self) -> bool:
        return self.attempts >= self.max_attempts


def next_action(check_passed: bool, budget: RetryBudget, risk_score: float = 0.0) -> str:
    if check_passed:
        return "RUN_FULL_PIPELINE"
    if risk_score >= 0.8:
        return "ESCALATE_HUMAN"
    if budget.consume():
        return "RETRY_WITH_ALTERNATIVE_HYPOTHESIS"
    return "ESCALATE_HUMAN"

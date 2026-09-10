"""Evaluation logic for repair proposals with retry budgets and risk-based decisions.

This module provides the evaluation layer that determines whether to accept repair
proposals, retry with alternative hypotheses, or escalate to human review based
on verification results, risk scores, and retry budgets.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetryBudget:
    """Budget manager for retry attempts during repair evaluation.

    This class tracks retry attempts and enforces a maximum limit to prevent
    infinite retry loops during autonomous repair operations.

    Attributes:
        max_attempts: Maximum number of retry attempts allowed (default: 3).
        attempts: Current number of retry attempts consumed.

    Audit Notes:
        - Exhausted retry budgets force escalation to human review.
        - Retry limits prevent infinite loops during autonomous repair.
        - Recovery: Review retry attempts and adjust max_attempts if needed.
        - Evidence: All retry budgets track attempt counts for audit trails.
    """

    max_attempts: int = 3
    attempts: int = 0

    def consume(self) -> bool:
        """Consume one retry attempt from the budget.

        Returns:
            True if a retry attempt was available and consumed, False if budget is exhausted.
        """
        if self.attempts >= self.max_attempts:
            return False
        self.attempts += 1
        return True

    @property
    def exhausted(self) -> bool:
        """Check if the retry budget is exhausted.

        Returns:
            True if no more retry attempts are available, False otherwise.
        """
        return self.attempts >= self.max_attempts


def next_action(check_passed: bool, budget: RetryBudget, risk_score: float = 0.0) -> str:
    """Determine the next action based on verification results and retry budget.

    This function implements the evaluation decision logic for repair proposals,
    balancing verification success, risk assessment, and retry budget constraints.

    Args:
        check_passed: Whether the verification check passed.
        budget: Retry budget tracking remaining retry attempts.
        risk_score: Risk score for the repair proposal (0.0 to 1.0, default: 0.0).

    Returns:
        String indicating the next action:
        - "RUN_FULL_PIPELINE": Verification passed, proceed with full pipeline.
        - "RETRY_WITH_ALTERNATIVE_HYPOTHESIS": Verification failed, retry available.
        - "ESCALATE_HUMAN": Verification failed, no retries or high risk.

    Decision Logic:
        - If verification passed: Run full pipeline.
        - If risk score >= 0.8: Escalate to human (high-risk threshold).
        - If retry budget available: Retry with alternative hypothesis.
        - Otherwise: Escalate to human (budget exhausted).

    Audit Notes:
        - High-risk proposals (>= 0.8) bypass retry and escalate immediately.
        - Exhausted retry budgets force escalation regardless of risk.
        - Recovery: Review risk scores and retry budget configuration.
        - Evidence: All decisions include check status, risk score, and budget state.
    """
    if check_passed:
        return "RUN_FULL_PIPELINE"
    if risk_score >= 0.8:
        return "ESCALATE_HUMAN"
    if budget.consume():
        return "RETRY_WITH_ALTERNATIVE_HYPOTHESIS"
    return "ESCALATE_HUMAN"

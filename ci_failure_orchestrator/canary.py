"""Canary deployment evaluation and control for CI repair rollouts.

This module provides canary deployment metrics, policy evaluation, and execution
control for gradual rollout of autonomous repair changes with rollback capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable


@dataclass(frozen=True)
class CanaryResult:
    """Result from a canary deployment execution.

    Attributes:
        deployed: Whether the canary was successfully deployed.
        healthy: Whether the canary passed health checks.
        rolled_back: Whether rollback was executed (if unhealthy).
        reason: Human-readable explanation of the result.
    """

    deployed: bool
    healthy: bool
    rolled_back: bool
    reason: str


class CanaryController:
    """Execution boundary for canary deploy/health/rollback hooks.

    This controller provides a small, bounded execution boundary for canary
    deployment operations, ensuring that deploy, health check, and rollback
    operations are executed in sequence with proper error handling.

    Attributes:
        deploy: Function to deploy the canary (returns True on success).
        health_check: Function to check canary health (returns True if healthy).
        rollback: Function to rollback the canary (returns True on success).

    Audit Notes:
        - Failed canary deployments or health checks should trigger rollback.
        - Rollback failures can leave the system in an inconsistent state.
        - Recovery: Review deployment logs and manually intervene if rollback fails.
        - Evidence: All canary results include deployment status and rollback status.
    """

    def __init__(
        self,
        deploy: Callable[[], bool],
        health_check: Callable[[], bool],
        rollback: Callable[[], bool],
    ):
        """Initialize the canary controller with execution hooks.

        Args:
            deploy: Function to deploy the canary (returns True on success).
            health_check: Function to check canary health (returns True if healthy).
            rollback: Function to rollback the canary (returns True on success).
        """
        self.deploy = deploy
        self.health_check = health_check
        self.rollback = rollback

    def run(self) -> CanaryResult:
        """Execute the canary deployment with health checks and rollback.

        This method attempts to deploy the canary, checks its health, and rolls
        back if the health check fails. It returns a detailed result for audit.

        Returns:
            CanaryResult with deployment status, health status, rollback status, and reason.

        Execution Flow:
            1. Attempt deployment. If failed, return with failure reason.
            2. Run health check. If passed, return success.
            3. If health check fails, attempt rollback and return result.

        Side Effects:
            - May deploy changes to the canary environment.
            - May execute rollback operations if health check fails.
        """
        if not self.deploy():
            return CanaryResult(False, False, False, "canary deployment failed")
        if self.health_check():
            return CanaryResult(True, True, False, "canary healthy")
        rolled_back = self.rollback()
        return CanaryResult(
            True,
            False,
            rolled_back,
            "canary unhealthy; rollback executed" if rolled_back else "canary unhealthy; rollback failed",
        )


class CanaryDecision(str, Enum):
    """Canary promotion decision.

    Attributes:
        PROMOTE: Canary is healthy and should be promoted to full rollout.
        HOLD: Canary is inconclusive (insufficient data or borderline metrics).
        ROLLBACK: Canary is unhealthy and should be rolled back immediately.
    """

    PROMOTE = "promote"
    HOLD = "hold"
    ROLLBACK = "rollback"


@dataclass(frozen=True)
class CanaryMetrics:
    """Metrics observed from a canary deployment.

    Attributes:
        sample_size: Number of canary instances or requests observed.
        success_rate: Proportion of successful canary operations.
        regression_rate: Proportion of canary operations that showed regression.
        false_repair_rate: Proportion of false positive repairs in canary.
        p95_latency_ms: 95th percentile latency in milliseconds.
    """

    sample_size: int
    success_rate: float
    regression_rate: float
    false_repair_rate: float
    p95_latency_ms: int


@dataclass(frozen=True)
class CanaryPolicy:
    """Policy thresholds for canary promotion decisions.

    Attributes:
        min_sample_size: Minimum sample size for statistical significance (default: 10).
        min_success_rate: Minimum success rate for promotion (default: 0.90).
        max_regression_rate: Maximum acceptable regression rate (default: 0.01).
        max_false_repair_rate: Maximum acceptable false repair rate (default: 0.02).
        max_p95_latency_ms: Maximum acceptable 95th percentile latency (default: 300,000 = 5 minutes).
    """

    min_sample_size: int = 10
    min_success_rate: float = 0.90
    max_regression_rate: float = 0.01
    max_false_repair_rate: float = 0.02
    max_p95_latency_ms: int = 300_000


def evaluate_canary(metrics: CanaryMetrics, policy: CanaryPolicy = CanaryPolicy()) -> CanaryDecision:
    """Evaluate canary metrics against policy to determine promotion decision.

    This function checks canary metrics against policy thresholds and returns
    a decision to promote, hold, or rollback the canary. Regression and false
    repair rate breaches trigger immediate rollback.

    Args:
        metrics: Observed canary deployment metrics.
        policy: Canary policy thresholds (defaults to conservative CanaryPolicy).

    Returns:
        CanaryDecision indicating whether to promote, hold, or rollback.

    Decision Logic:
        - ROLLBACK: Regression rate or false repair rate exceeds policy threshold.
        - HOLD: Sample size insufficient, success rate below threshold, or latency too high.
        - PROMOTE: All metrics meet or exceed policy thresholds.

    Audit Notes:
        - Rollback decisions are triggered by regression or false repair rate breaches.
        - Hold decisions indicate insufficient data or borderline performance.
        - Recovery: Review canary metrics and adjust policy thresholds if needed.
        - Evidence: All canary evaluations include metrics comparison against policy.
    """
    if metrics.regression_rate > policy.max_regression_rate:
        return CanaryDecision.ROLLBACK
    if metrics.false_repair_rate > policy.max_false_repair_rate:
        return CanaryDecision.ROLLBACK
    if metrics.sample_size < policy.min_sample_size:
        return CanaryDecision.HOLD
    if metrics.success_rate < policy.min_success_rate:
        return CanaryDecision.HOLD
    if metrics.p95_latency_ms > policy.max_p95_latency_ms:
        return CanaryDecision.HOLD
    return CanaryDecision.PROMOTE

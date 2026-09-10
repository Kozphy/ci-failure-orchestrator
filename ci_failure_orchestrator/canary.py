from __future__ import annotations

"""Canary deployment controller and evaluation for CI repair platform.

This module provides canary deployment execution boundaries and
health-based promotion/rollback decisions. It enforces the safety
invariant that regressions or unhealthy canaries must trigger rollback
rather than promotion.

Module responsibility:
    - Execute canary deployment with deploy/health/rollback hooks
    - Evaluate canary metrics against policy thresholds
    - Return deterministic promotion, hold, or rollback decisions

Key invariants:
    - CanaryController.run() executes hooks in order: deploy -> health_check -> rollback
    - Canary rollback takes precedence over all other considerations
    - Health check failure automatically triggers rollback attempt

Safety boundaries:
    - CanaryController hooks are Callable[[], bool] - simple success/failure
    - No automatic retry on hook failures
    - Rollback failure is surfaced in CanaryResult.rolled_back=False

Failure modes:
    - deploy() fails: CanaryResult(deployed=False, healthy=False, rolled_back=False, reason="canary deployment failed")
    - health_check() fails: triggers rollback(), returns rollback result
    - rollback() fails: CanaryResult(rolled_back=False, reason="canary unhealthy; rollback failed")

Audit Notes:
    - CanaryDecision.ROLLBACK must trigger fleet freeze in platform layer
    - Canary metrics are pre-computed; evaluate_canary() does not fetch live data
    - Policy thresholds are conservative defaults
"""

from dataclasses import dataclass
from enum import Enum
from typing import Callable


@dataclass(frozen=True)
class CanaryResult:
    """Result of a canary deployment execution.

    Attributes:
        deployed: Whether the canary was successfully deployed
        healthy: Whether the canary passed health checks
        rolled_back: Whether rollback was successfully executed
        reason: Human-readable explanation of the result
    """

    deployed: bool
    healthy: bool
    rolled_back: bool
    reason: str


class CanaryController:
    """Execution boundary for canary deploy/health/rollback operations.

    Provides a small, testable interface for canary deployment workflows.
    The controller executes hooks in a fixed sequence and returns a
    CanaryResult describing the outcome.

    Responsibility:
        - Execute deploy, health_check, and rollback hooks in sequence
        - Capture success/failure of each operation
        - Return a complete CanaryResult for audit purposes

    Invariants:
        - If deploy fails, health_check and rollback are NOT executed
        - If health_check fails, rollback IS executed
        - Hooks are simple Callable[[], bool] with no retry logic

    Usage:
        controller = CanaryController(
            deploy=lambda: deploy_to_staging(),
            health_check=lambda: check_health(),
            rollback=lambda: rollback_to_stable(),
        )
        result = controller.run()

    Side effects:
        - Deploy hook may mutate external systems
        - Rollback hook may mutate external systems

    Audit Notes:
        - Hook execution order is deterministic
        - All outcomes are captured in CanaryResult
        - No automatic retry on failures
    """

    def __init__(
        self,
        deploy: Callable[[], bool],
        health_check: Callable[[], bool],
        rollback: Callable[[], bool],
    ):
        """Initialize with execution hooks.

        Args:
            deploy: Callable that attempts canary deployment, returns True on success
            health_check: Callable that checks canary health, returns True if healthy
            rollback: Callable that rolls back to previous version, returns True on success
        """
        self.deploy = deploy
        self.health_check = health_check
        self.rollback = rollback

    def run(self) -> CanaryResult:
        """Execute canary deployment workflow.

        Sequence:
        1. Attempt deploy
        2. If deploy fails: return failure result (no health check or rollback)
        3. If deploy succeeds: run health check
        4. If health check passes: return healthy result
        5. If health check fails: attempt rollback and return result

        Returns:
            CanaryResult describing the complete outcome

        Side effects:
            - May execute deploy hook (mutates external state)
            - May execute rollback hook (mutates external state)

        Audit Notes:
            - Health check failure always triggers rollback attempt
            - Rollback failure is captured in result.rolled_back
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
    """Decision outcome for canary evaluation.

    Values:
        PROMOTE: Canary passed all health checks, ready for promotion
        HOLD: Canary is healthy but does not meet promotion criteria
        ROLLBACK: Canary has regressions or failures, must roll back
    """

    PROMOTE = "promote"
    HOLD = "hold"
    ROLLBACK = "rollback"


@dataclass(frozen=True)
class CanaryMetrics:
    """Health metrics for canary evaluation.

    Attributes:
        sample_size: Number of repair cases in the canary sample
        success_rate: Fraction of successful repairs in the sample (0.0-1.0)
        regression_rate: Fraction of repairs that introduced regressions (0.0-1.0)
        false_repair_rate: Fraction of false repairs in the sample (0.0-1.0)
        p95_latency_ms: 95th percentile repair latency in milliseconds
    """

    sample_size: int
    success_rate: float
    regression_rate: float
    false_repair_rate: float
    p95_latency_ms: int


@dataclass(frozen=True)
class CanaryPolicy:
    """Threshold policy for canary promotion decisions.

    Defines the minimum acceptable metrics for canary promotion.
    Any metric exceeding its maximum threshold triggers ROLLBACK.

    Attributes:
        min_sample_size: Minimum number of samples required for promotion
        min_success_rate: Minimum success rate for promotion
        max_regression_rate: Maximum acceptable regression rate
        max_false_repair_rate: Maximum acceptable false repair rate
        max_p95_latency_ms: Maximum acceptable 95th percentile latency
    """

    min_sample_size: int = 10
    min_success_rate: float = 0.90
    max_regression_rate: float = 0.01
    max_false_repair_rate: float = 0.02
    max_p95_latency_ms: int = 300_000


def evaluate_canary(metrics: CanaryMetrics, policy: CanaryPolicy = CanaryPolicy()) -> CanaryDecision:
    """Evaluate canary metrics against policy and return decision.

    Uses fail-closed semantics: any policy violation triggers ROLLBACK,
    insufficient sample or metrics triggers HOLD, otherwise PROMOTE.

    Priority order (checked first to last):
    1. regression_rate > max_regression_rate -> ROLLBACK
    2. false_repair_rate > max_false_repair_rate -> ROLLBACK
    3. sample_size < min_sample_size -> HOLD
    4. success_rate < min_success_rate -> HOLD
    5. p95_latency_ms > max_p95_latency_ms -> HOLD
    6. Otherwise -> PROMOTE

    Args:
        metrics: CanaryMetrics containing observed health data
        policy: CanaryPolicy defining thresholds; defaults to standard policy

    Returns:
        CanaryDecision.PROMOTE, HOLD, or ROLLBACK

    Side effects:
        None. Pure computation from inputs.

    Audit Notes:
        - ROLLBACK takes precedence over all other decisions
        - HOLD is returned for any insufficient metric
        - PROMOTE requires all metrics to pass all thresholds
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

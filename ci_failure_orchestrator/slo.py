"""Service Level Objectives (SLOs) and error-budget tracking for CI repair.

This module provides SLO target definitions, observation metrics, and evaluation
logic for CI repair operations, including error-budget burn calculation and
violation detection.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SLOTarget:
    """Service Level Objective targets for CI repair operations.

    Attributes:
        availability: Target workflow availability (default: 0.99 = 99%).
        repair_success_rate: Target proportion of successful repairs (default: 0.90).
        p95_repair_latency_ms: Target 95th percentile repair latency in ms (default: 300,000 = 5 minutes).
        false_repair_rate: Target maximum false repair rate (default: 0.02 = 2%).
    """

    availability: float = 0.99
    repair_success_rate: float = 0.90
    p95_repair_latency_ms: int = 300_000
    false_repair_rate: float = 0.02


@dataclass(frozen=True)
class SLOObservation:
    """Observed SLO metrics from CI repair operations.

    Attributes:
        total_runs: Total number of CI workflow runs.
        successful_runs: Number of successful workflow runs.
        successful_repairs: Number of successful repair operations.
        attempted_repairs: Number of attempted repair operations.
        false_repairs: Number of false positive repairs.
        p95_repair_latency_ms: Observed 95th percentile repair latency in milliseconds.

    Computed Properties:
        availability: Proportion of successful workflow runs.
        repair_success_rate: Proportion of successful repairs among attempts.
        false_repair_rate: Proportion of false repairs among attempts.
    """

    total_runs: int
    successful_runs: int
    successful_repairs: int
    attempted_repairs: int
    false_repairs: int
    p95_repair_latency_ms: int

    @property
    def availability(self) -> float:
        """Calculate workflow availability from successful runs."""
        return self.successful_runs / self.total_runs if self.total_runs else 1.0

    @property
    def repair_success_rate(self) -> float:
        """Calculate repair success rate from successful repairs."""
        return self.successful_repairs / self.attempted_repairs if self.attempted_repairs else 1.0

    @property
    def false_repair_rate(self) -> float:
        """Calculate false repair rate from false repairs."""
        return self.false_repairs / self.attempted_repairs if self.attempted_repairs else 0.0


@dataclass(frozen=True)
class SLOReport:
    """Report from SLO evaluation against targets.

    Attributes:
        met: Whether all SLO targets were met.
        availability: Observed workflow availability.
        repair_success_rate: Observed repair success rate.
        false_repair_rate: Observed false repair rate.
        p95_repair_latency_ms: Observed 95th percentile repair latency.
        error_budget_burn: Error-budget burn rate (1.0 = budget exhausted).
        violations: Tuple of SLO metric names that violated targets.
    """

    met: bool
    availability: float
    repair_success_rate: float
    false_repair_rate: float
    p95_repair_latency_ms: int
    error_budget_burn: float
    violations: tuple[str, ...]


def evaluate_slo(target: SLOTarget, observation: SLOObservation) -> SLOReport:
    """Evaluate observed metrics against SLO targets.

    This function checks each SLO metric against its target, calculates error-budget
    burn, and returns a comprehensive report with violation details.

    Args:
        target: SLO targets to evaluate against.
        observation: Observed metrics from CI repair operations.

    Returns:
        SLOReport with evaluation results, error-budget burn, and violation list.

    Error Budget Calculation:
        Error-budget burn is the ratio of observed unavailability to allowed unavailability.
        A burn rate of 1.0 means the error budget is exhausted. Rates above 1.0 indicate
        the budget has been exceeded and may trigger fleet freeze.

    Audit Notes:
        - SLO violations can trigger fleet-wide freeze of autonomous repair.
        - Error-budget burn calculation assumes monotonic time windows.
        - Recovery: Review violation metrics and error-budget calculations before unfreezing.
        - Evidence: All SLO evaluations produce violation lists and burn rates for audit.
    """
    violations: list[str] = []
    if observation.availability < target.availability:
        violations.append("availability")
    if observation.repair_success_rate < target.repair_success_rate:
        violations.append("repair_success_rate")
    if observation.false_repair_rate > target.false_repair_rate:
        violations.append("false_repair_rate")
    if observation.p95_repair_latency_ms > target.p95_repair_latency_ms:
        violations.append("p95_repair_latency")

    allowed_unavailability = max(1e-9, 1.0 - target.availability)
    observed_unavailability = max(0.0, 1.0 - observation.availability)
    burn = observed_unavailability / allowed_unavailability

    return SLOReport(
        met=not violations,
        availability=observation.availability,
        repair_success_rate=observation.repair_success_rate,
        false_repair_rate=observation.false_repair_rate,
        p95_repair_latency_ms=observation.p95_repair_latency_ms,
        error_budget_burn=burn,
        violations=tuple(violations),
    )

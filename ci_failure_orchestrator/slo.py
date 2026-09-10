from __future__ import annotations

"""Service Level Objective (SLO) evaluation for CI repair platform.

This module provides SLO target definition, observation recording, and
compliance evaluation with error-budget burn calculation. It supports
the platform's safety invariant that autonomous repair must be frozen when
reliability targets are not being met.

Module responsibility:
    - Define SLO targets (availability, repair success, latency, false repair rate)
    - Compute observed metrics from field data
    - Evaluate compliance against targets
    - Calculate error-budget burn ratio

Key invariants:
    - All metrics are normalized to ratios (0.0 to 1.0) where appropriate
    - Error-budget burn is computed as observed_unavailability / allowed_unavailability
    - Empty observation data defaults to safe values (1.0 for availability, 0.0 for error rates)

Failure modes:
    - Division by zero: protected by max(1e-9, ...) for availability and max(0.0, ...) for unavailability
    - Zero attempted repairs: repair_success_rate and false_repair_rate return 1.0 and 0.0 respectively

Safety boundaries:
    - SLO evaluation is fail-closed: any violation means SLO is not met
    - Error-budget burn calculation uses conservative defaults

Audit Notes:
    - SLOReport.met is the authoritative signal for fleet freeze decisions
    - violations tuple contains all SLO dimensions that failed
    - error_budget_burn > 1.0 means the budget is exhausted
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SLOTarget:
    """Target SLO thresholds for CI repair platform reliability.

    Defines the acceptable performance boundaries for the repair system.
    Exceeding any threshold constitutes an SLO violation.

    Attributes:
        availability: Target fraction of successful workflow runs (0.0-1.0)
        repair_success_rate: Target fraction of successful repairs among attempted repairs (0.0-1.0)
        p95_repair_latency_ms: Target 95th percentile repair latency in milliseconds
        false_repair_rate: Target maximum fraction of false repairs among attempted repairs (0.0-1.0)
    """

    availability: float = 0.99
    repair_success_rate: float = 0.90
    p95_repair_latency_ms: int = 300_000
    false_repair_rate: float = 0.02


@dataclass(frozen=True)
class SLOObservation:
    """Observed SLO metrics from the field.

    Captures actual measurements of platform reliability for comparison
    against SLO targets.

    Attributes:
        total_runs: Total number of workflow runs observed
        successful_runs: Number of workflow runs that completed successfully
        successful_repairs: Number of repair attempts that succeeded
        attempted_repairs: Total number of repair attempts made
        false_repairs: Number of repairs that introduced regressions
        p95_repair_latency_ms: Observed 95th percentile repair latency in milliseconds
    """

    total_runs: int
    successful_runs: int
    successful_repairs: int
    attempted_repairs: int
    false_repairs: int
    p95_repair_latency_ms: int

    @property
    def availability(self) -> float:
        """Compute observed availability ratio.

        Returns:
            successful_runs / total_runs, or 1.0 if total_runs is 0
        """
        return self.successful_runs / self.total_runs if self.total_runs else 1.0

    @property
    def repair_success_rate(self) -> float:
        """Compute observed repair success ratio.

        Returns:
            successful_repairs / attempted_repairs, or 1.0 if attempted_repairs is 0
        """
        return self.successful_repairs / self.attempted_repairs if self.attempted_repairs else 1.0

    @property
    def false_repair_rate(self) -> float:
        """Compute observed false repair ratio.

        Returns:
            false_repairs / attempted_repairs, or 0.0 if attempted_repairs is 0
        """
        return self.false_repairs / self.attempted_repairs if self.attempted_repairs else 0.0


@dataclass(frozen=True)
class SLOReport:
    """Result of SLO compliance evaluation.

    Combines observed metrics with violation status and error-budget
    burn calculation.

    Attributes:
        met: True if all SLO targets are satisfied, False otherwise
        availability: Observed availability ratio
        repair_success_rate: Observed repair success ratio
        false_repair_rate: Observed false repair ratio
        p95_repair_latency_ms: Observed 95th percentile latency
        error_budget_burn: Ratio of error budget consumed (0.0 to infinity)
        violations: Tuple of SLO dimension names that failed ("availability", "repair_success_rate", etc.)
    """

    met: bool
    availability: float
    repair_success_rate: float
    false_repair_rate: float
    p95_repair_latency_ms: int
    error_budget_burn: float
    violations: tuple[str, ...]


def evaluate_slo(target: SLOTarget, observation: SLOObservation) -> SLOReport:
    """Evaluate SLO compliance and compute error-budget burn.

    Compares observed metrics against target thresholds and calculates
    the error-budget burn ratio. The burn ratio is computed as:
    observed_unavailability / allowed_unavailability

    where allowed_unavailability = 1.0 - target.availability

    Args:
        target: SLOTarget defining acceptable thresholds
        observation: SLOObservation containing field measurements

    Returns:
        SLOReport with compliance status, observed metrics, burn ratio, and violations

    Side effects:
        None. Pure computation from inputs.

    Audit Notes:
        - violations tuple is empty when all targets are met
        - error_budget_burn > 1.0 indicates budget exhaustion
        - Any non-empty violations means report.met is False
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

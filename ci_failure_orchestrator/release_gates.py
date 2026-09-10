"""Canonical promotion gates for repair, release, and production success.

The three predicates are deliberately layered. A later stage can never become
successful unless the previous stage has already satisfied its canonical contract.
This prevents deployment or production health from masking an unsafe repair.
"""

from __future__ import annotations

from dataclasses import dataclass

from .repair_state_machine import VerificationResult


@dataclass(frozen=True)
class ReleaseReadinessResult:
    """Independent evidence required before a verified repair may be released."""

    repair: VerificationResult
    artifact_integrity_passed: bool
    dependency_gate_passed: bool
    deployment_validation_passed: bool
    required_approvals_passed: bool
    rollback_ready: bool

    @property
    def ready(self) -> bool:
        """Return the canonical RELEASE_READY predicate."""

        return (
            self.repair.successful
            and self.artifact_integrity_passed
            and self.dependency_gate_passed
            and self.deployment_validation_passed
            and self.required_approvals_passed
            and self.rollback_ready
        )


@dataclass(frozen=True)
class ProductionSuccessResult:
    """Independent production evidence required after release readiness."""

    release: ReleaseReadinessResult
    canary_healthy: bool
    slo_passed: bool
    error_budget_ok: bool
    observability_healthy: bool
    production_regression_detected: bool = False

    @property
    def successful(self) -> bool:
        """Return the canonical PRODUCTION_SUCCESS predicate."""

        return (
            self.release.ready
            and self.canary_healthy
            and self.slo_passed
            and self.error_budget_ok
            and self.observability_healthy
            and not self.production_regression_detected
        )


def repair_success(result: VerificationResult) -> bool:
    """Expose the canonical REPAIR_SUCCESS predicate as a named gate."""

    return result.successful


def release_ready(result: ReleaseReadinessResult) -> bool:
    """Expose the canonical RELEASE_READY predicate as a named gate."""

    return result.ready


def production_success(result: ProductionSuccessResult) -> bool:
    """Expose the canonical PRODUCTION_SUCCESS predicate as a named gate."""

    return result.successful

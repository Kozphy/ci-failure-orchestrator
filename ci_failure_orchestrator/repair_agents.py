"""Specialized repair agents for different CI failure types.

This module provides deterministic repair agents that propose repair strategies
for specific failure categories such as type errors, test failures, security
issues, and general coding problems.
"""

from __future__ import annotations

from .control_plane import RepairProposal
from .graph import PipelineGraph
from .models import Failure


class DeterministicRepairAgent:
    """Deterministic repair agent for infrastructure and configuration errors.

    This agent handles deterministic failure types with known repair strategies,
    such as type errors, dependency issues, build failures, and network errors.
    """

    name = "deterministic"

    def propose(self, failure: Failure, graph: PipelineGraph) -> RepairProposal | None:
        """Propose a repair strategy for deterministic failure types.

        Args:
            failure: The failure to repair.
            graph: Pipeline dependency graph (unused for deterministic strategies).

        Returns:
            RepairProposal with strategy, stage, confidence, cost, and latency estimates,
            or None if the failure type is not handled by this agent.

        Supported Strategies:
            - TYPE_ERROR: type_fix
            - DEPENDENCY_ERROR: dependency_reconcile
            - BUILD_ERROR: build_config_fix
            - PACKAGE_ERROR: package_rebuild
            - NETWORK_ERROR: bounded_infra_retry
        """
        strategies = {
            "TYPE_ERROR": "type_fix",
            "DEPENDENCY_ERROR": "dependency_reconcile",
            "BUILD_ERROR": "build_config_fix",
            "PACKAGE_ERROR": "package_rebuild",
            "NETWORK_ERROR": "bounded_infra_retry",
        }
        strategy = strategies.get(failure.error_type)
        if not strategy:
            return None
        return RepairProposal(self.name, strategy, failure.stage, 0.92, estimated_cost=0.02, expected_latency_ms=250)


class TestRepairAgent:
    """Specialized repair agent for test failures and flaky tests.

    This agent handles test assertion failures, flaky tests, and runtime errors
    with appropriate strategies such as targeted test repair or quarantine and retry.
    """

    name = "test-agent"

    def propose(self, failure: Failure, graph: PipelineGraph) -> RepairProposal | None:
        """Propose a repair strategy for test-related failures.

        Args:
            failure: The failure to repair.
            graph: Pipeline dependency graph (unused for test strategies).

        Returns:
            RepairProposal with strategy, stage, confidence, cost, and latency estimates,
            or None if the failure type is not test-related.

        Supported Strategies:
            - FLAKY_TEST: quarantine_and_retry
            - TEST_ASSERTION/RUNTIME_ERROR: targeted_test_repair
        """
        if failure.error_type not in {"TEST_ASSERTION", "FLAKY_TEST", "RUNTIME_ERROR"}:
            return None
        strategy = "quarantine_and_retry" if failure.error_type == "FLAKY_TEST" else "targeted_test_repair"
        return RepairProposal(self.name, strategy, failure.stage, 0.82, estimated_cost=0.08, expected_latency_ms=800)


class SecurityRepairAgent:
    """Specialized repair agent for security-related failures.

    This agent handles security errors with safe dependency upgrade strategies,
    prioritizing security policy enforcement over quick fixes.
    """

    name = "security-agent"

    def propose(self, failure: Failure, graph: PipelineGraph) -> RepairProposal | None:
        """Propose a repair strategy for security failures.

        Args:
            failure: The failure to repair.
            graph: Pipeline dependency graph (unused for security strategies).

        Returns:
            RepairProposal with safe dependency upgrade strategy, or None if the
            failure type is not SECURITY_ERROR.

        Strategy:
            - SECURITY_ERROR: safe_dependency_upgrade
        """
        if failure.error_type != "SECURITY_ERROR":
            return None
        return RepairProposal(self.name, "safe_dependency_upgrade", failure.stage, 0.78, estimated_cost=0.10, expected_latency_ms=1200)


class GeneralCodingAgent:
    """General-purpose coding agent for unknown or complex failures.

    This agent handles any failure type except UNKNOWN, using agentic patching
    with confidence adjusted based on the downstream impact in the pipeline graph.
    """

    name = "general-coding-agent"

    def propose(self, failure: Failure, graph: PipelineGraph) -> RepairProposal | None:
        """Propose a repair strategy for general coding failures.

        Args:
            failure: The failure to repair.
            graph: Pipeline dependency graph used to estimate downstream impact.

        Returns:
            RepairProposal with agentic patch strategy, or None if the failure
            type is UNKNOWN.

        Strategy:
            - All non-UNKNOWN types: agentic_patch

        Confidence Calculation:
            Confidence increases with downstream impact (more affected stages = higher confidence).
            Base confidence: 0.55, maximum: 0.75, increment: 0.03 per downstream stage.
        """
        if failure.error_type == "UNKNOWN":
            return None
        downstream = len(graph.descendants(failure.stage))
        confidence = min(0.75, 0.55 + downstream * 0.03)
        return RepairProposal(self.name, "agentic_patch", failure.stage, confidence, estimated_cost=0.25, expected_latency_ms=2500)

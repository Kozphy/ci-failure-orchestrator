from __future__ import annotations

from .control_plane import RepairProposal
from .graph import PipelineGraph
from .models import Failure


class DeterministicRepairAgent:
    name = "deterministic"

    def propose(self, failure: Failure, graph: PipelineGraph) -> RepairProposal | None:
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
    name = "test-agent"

    def propose(self, failure: Failure, graph: PipelineGraph) -> RepairProposal | None:
        if failure.error_type not in {"TEST_ASSERTION", "FLAKY_TEST", "RUNTIME_ERROR"}:
            return None
        strategy = "quarantine_and_retry" if failure.error_type == "FLAKY_TEST" else "targeted_test_repair"
        return RepairProposal(self.name, strategy, failure.stage, 0.82, estimated_cost=0.08, expected_latency_ms=800)


class SecurityRepairAgent:
    name = "security-agent"

    def propose(self, failure: Failure, graph: PipelineGraph) -> RepairProposal | None:
        if failure.error_type != "SECURITY_ERROR":
            return None
        return RepairProposal(self.name, "safe_dependency_upgrade", failure.stage, 0.78, estimated_cost=0.10, expected_latency_ms=1200)


class GeneralCodingAgent:
    name = "general-coding-agent"

    def propose(self, failure: Failure, graph: PipelineGraph) -> RepairProposal | None:
        if failure.error_type == "UNKNOWN":
            return None
        downstream = len(graph.descendants(failure.stage))
        confidence = min(0.75, 0.55 + downstream * 0.03)
        return RepairProposal(self.name, "agentic_patch", failure.stage, confidence, estimated_cost=0.25, expected_latency_ms=2500)

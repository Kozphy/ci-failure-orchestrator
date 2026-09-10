"""Memory-aware repair planning with bounded historical evidence.

This module provides a repair planner that decorates the deterministic planner
with bounded historical evidence from the failure memory system. It retrieves
similar past incidents, separates successful repairs from regressive attempts,
and augments repair plans with historical context while never granting repair
or release authority based solely on historical data.
"""

from __future__ import annotations

from dataclasses import replace

from .failure_memory import FailureMemoryAgent, MemoryQuery
from .graph import PipelineGraph
from .models import RankedFailure
from .repair_planner import DeterministicRepairPlanner, RepairPlan


class MemoryAwareRepairPlanner:
    """Decorates the deterministic planner with bounded historical evidence.

    This planner enhances the base deterministic planner by retrieving similar
    historical incidents from the failure memory and augmenting repair plans with
    historical context. It strictly enforces that historical incidents are advisory
    evidence only and never grant repair or release authority.

    Attributes:
        memory: FailureMemoryAgent for historical incident retrieval.
        base: Base deterministic planner (defaults to DeterministicRepairPlanner).
        retrieval_limit: Maximum number of similar incidents to retrieve (default: 5).
        minimum_similarity: Minimum similarity threshold for historical matches (default: 0.25).

    Audit Notes:
        - Historical incidents are advisory evidence only, not execution authority.
        - Regression-producing fixes are separated and never promoted in historical context.
        - Memory context is added to metadata for audit trails but does not bypass safety checks.
        - Recovery: Review similarity thresholds and retrieval limits if memory quality is poor.
        - Evidence: All plans include memory context with match counts and similarity scores.

    Engineering Notes:
        - Trade-off: Memory adds context but may introduce bias from past failures.
        - Design: Historical repairs are appended to proposed_change as advisory evidence.
        - Performance: Memory retrieval adds latency but provides valuable context for repair decisions.
    """

    def __init__(
        self,
        memory: FailureMemoryAgent,
        base: DeterministicRepairPlanner | None = None,
        *,
        retrieval_limit: int = 5,
        minimum_similarity: float = 0.25,
    ) -> None:
        """Initialize the memory-aware repair planner.

        Args:
            memory: FailureMemoryAgent for historical incident retrieval.
            base: Optional base deterministic planner. Defaults to DeterministicRepairPlanner.
            retrieval_limit: Maximum number of similar incidents to retrieve (default: 5).
            minimum_similarity: Minimum similarity threshold for historical matches (default: 0.25).
        """
        self.memory = memory
        self.base = base or DeterministicRepairPlanner()
        self.retrieval_limit = retrieval_limit
        self.minimum_similarity = minimum_similarity

    def plan(
        self,
        graph: PipelineGraph,
        ranked_failure: RankedFailure,
        failed_stages: set[str],
    ) -> RepairPlan:
        """Generate a repair plan enhanced with historical evidence.

        This method first generates a base plan using the deterministic planner,
        then retrieves similar historical incidents from the failure memory,
        and augments the plan with historical context including successful
        repair summaries and similarity scores.

        Args:
            graph: Pipeline dependency graph for verification planning.
            ranked_failure: Ranked failure with root-cause hypothesis and metadata.
            failed_stages: Set of all failed stage IDs for verification planning.

        Returns:
            RepairPlan with base deterministic plan augmented with memory context.

        Memory Enhancement:
            - Retrieves similar incidents based on error signature, failure class, root stage, and files.
            - Separates successful repairs from regressive attempts.
            - Appends historical repair summaries to proposed_change as advisory evidence.
            - Adds memory context metadata with match counts and similarity scores.

        Safety Invariants:
            - Historical incidents never override deterministic playbook decisions.
            - Regression-producing fixes are never promoted in historical context.
            - Memory context is metadata only and does not bypass safety checks.
        """
        base_plan = self.base.plan(graph, ranked_failure, failed_stages)
        failure = ranked_failure.failure
        files = tuple(str(path) for path in failure.metadata.get("files", []) if isinstance(path, str))
        query = MemoryQuery(
            error_signature=failure.message or failure.error_type,
            failure_class=failure.error_type,
            root_stage=failure.stage,
            changed_files=files,
        )
        retrieved = self.memory.retrieve(
            query,
            limit=self.retrieval_limit,
            min_similarity=self.minimum_similarity,
        )
        summary = self.memory.summarize(retrieved)
        historical_repairs = tuple(summary.get("historical_repairs", ()))
        top_similarity = retrieved[0].similarity if retrieved else 0.0
        regression_matches = sum(1 for item in retrieved if item.incident.regression_detected)

        memory_context = (
            f"memory_matches={len(retrieved)}; "
            f"successful_matches={summary.get('successful_matches', 0)}; "
            f"top_similarity={top_similarity:.3f}; "
            f"regression_matches={regression_matches}"
        )
        proposed_change = base_plan.proposed_change
        if historical_repairs:
            proposed_change = (
                f"{proposed_change}. Historical successful repair evidence: "
                + " | ".join(historical_repairs[:3])
            )

        metadata = dict(base_plan.metadata)
        metadata.update({
            "memory_context": memory_context,
            "memory_matches": str(len(retrieved)),
            "memory_successful_matches": str(summary.get("successful_matches", 0)),
            "memory_top_similarity": f"{top_similarity:.3f}",
            "memory_regression_matches": str(regression_matches),
        })
        return replace(
            base_plan,
            proposed_change=proposed_change,
            metadata=metadata,
        )

from __future__ import annotations

from dataclasses import replace

from .failure_memory import FailureMemoryAgent, MemoryQuery
from .graph import PipelineGraph
from .models import RankedFailure
from .repair_planner import DeterministicRepairPlanner, RepairPlan


class MemoryAwareRepairPlanner:
    """Decorates the deterministic planner with bounded historical evidence."""

    def __init__(
        self,
        memory: FailureMemoryAgent,
        base: DeterministicRepairPlanner | None = None,
        *,
        retrieval_limit: int = 5,
        minimum_similarity: float = 0.25,
    ) -> None:
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

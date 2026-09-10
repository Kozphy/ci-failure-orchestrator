from __future__ import annotations

"""Verification planning for CI repair validation.

This module generates a prioritized verification plan that balances
targeted testing of the proposed fix against full regression protection.
It ensures that repairs are validated efficiently without sacrificing safety.

Module responsibility:
    - Generate prioritized verification steps
    - Balance targeted and full-pipeline verification
    - Ensure root cause and downstream fixes are validated

Key invariants:
    - Root stage is always verified first
    - Downstream impacted stages are verified in depth order
    - Full pipeline verification is always last

Safety boundaries:
    - Unknown stage raises ValueError (fail-fast)
    - All failed stages in the causal path are verified
    - Full pipeline guard is always included

Audit Notes:
    - Verification plan is deterministic given the same inputs
    - Targeted verification reduces cost and latency
    - Full pipeline verification prevents regressions outside causal path
"""

from dataclasses import dataclass, asdict

from .graph import PipelineGraph


@dataclass(frozen=True)
class VerificationStep:
    """Single step in a verification plan.

    Attributes:
        stage: Stage ID to verify, or "*" for full pipeline
        scope: Verification scope ("targeted" or "full-pipeline")
        reason: Human-readable explanation for this step
    """

    stage: str
    scope: str
    reason: str

    def to_dict(self):
        """Return JSON-serializable dictionary representation.

        Returns:
            Dictionary with all step fields
        """
        return asdict(self)


def plan_verification(graph: PipelineGraph, root_stage: str, failed_stages: set[str]) -> list[VerificationStep]:
    """Generate a prioritized verification plan.

    Creates a plan that:
    1. First verifies the proposed root cause stage
    2. Then verifies all downstream impacted stages (sorted by depth)
    3. Finally runs full pipeline verification as a regression guard

    Args:
        graph: PipelineGraph for stage dependency context
        root_stage: The proposed root cause stage to verify first
        failed_stages: Set of all stage IDs that have failures

    Returns:
        List of VerificationStep in execution order

    Raises:
        ValueError: If root_stage is not in the graph

    Side effects:
        None.

    Audit Notes:
        - Root stage verification is always first
        - Downstream stages are verified in depth order (shallow first)
        - Full pipeline verification catches regressions outside causal path
    """
    if root_stage not in graph.stages:
        raise ValueError(f"Unknown stage: {root_stage}")
    steps = [VerificationStep(root_stage, "targeted", "verify the proposed root-cause fix first")]
    impacted = sorted(graph.descendants(root_stage) & failed_stages, key=lambda stage: graph.depth(stage))
    for stage in impacted:
        steps.append(VerificationStep(stage, "targeted", "confirm predicted downstream failure disappears"))
    steps.append(VerificationStep("*", "full-pipeline", "guard against regressions outside the causal path"))
    return steps

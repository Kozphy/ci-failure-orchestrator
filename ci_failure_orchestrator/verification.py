"""Verification planning for CI repair operations.

This module provides verification step planning that ensures comprehensive test
coverage for repair proposals, including targeted verification of the root cause
and affected downstream stages, plus full regression testing to guard against
unintended side effects.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from .graph import PipelineGraph

@dataclass(frozen=True)
class VerificationStep:
    """Single verification step in a repair verification plan.

    Attributes:
        stage: Stage ID to verify (or "*" for full pipeline).
        scope: Verification scope (e.g., "targeted", "full-pipeline").
        reason: Human-readable explanation of why this step is needed.
    """

    stage: str
    scope: str
    reason: str

    def to_dict(self):
        """Convert the verification step to a dictionary representation.

        Returns:
            Dictionary containing stage, scope, and reason fields.
        """
        return asdict(self)


def plan_verification(graph: PipelineGraph, root_stage: str, failed_stages: set[str]) -> list[VerificationStep]:
    """Generate a verification plan for a root-cause repair.

    This function creates a comprehensive verification plan that includes:
    1. Targeted verification of the root-cause stage
    2. Targeted verification of impacted downstream stages
    3. Full regression testing to guard against unintended side effects

    Args:
        graph: Pipeline dependency graph for stage relationship analysis.
        root_stage: The root-cause stage where the repair is applied.
        failed_stages: Set of all failed stage IDs in the current incident.

    Returns:
        List of VerificationStep objects in execution order.

    Raises:
        ValueError: If root_stage is not in the pipeline graph.

    Verification Plan:
        - First: Verify the root-cause stage fix (targeted).
        - Next: Verify impacted downstream stages in depth order (targeted).
        - Last: Run full regression suite (full-pipeline) to catch regressions.

    Audit Notes:
        - Skipping verification steps could release untested or dangerous changes.
        - Full regression testing is mandatory to catch regressions outside the causal path.
        - Recovery: Review verification plan and ensure all steps are executed.
        - Evidence: All verification plans include stage scope and reasoning for audit.
    """
    if root_stage not in graph.stages:
        raise ValueError(f"Unknown stage: {root_stage}")
    steps = [VerificationStep(root_stage, "targeted", "verify the proposed root-cause fix first")]
    impacted = sorted(graph.descendants(root_stage) & failed_stages, key=lambda stage: graph.depth(stage))
    for stage in impacted:
        steps.append(VerificationStep(stage, "targeted", "confirm predicted downstream failure disappears"))
    steps.append(VerificationStep("*", "full-pipeline", "guard against regressions outside the causal path"))
    return steps

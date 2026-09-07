from __future__ import annotations
from dataclasses import dataclass, asdict
from .graph import PipelineGraph

@dataclass(frozen=True)
class VerificationStep:
    stage: str
    scope: str
    reason: str

    def to_dict(self):
        return asdict(self)


def plan_verification(graph: PipelineGraph, root_stage: str, failed_stages: set[str]) -> list[VerificationStep]:
    if root_stage not in graph.stages:
        raise ValueError(f"Unknown stage: {root_stage}")
    steps = [VerificationStep(root_stage, "targeted", "verify the proposed root-cause fix first")]
    impacted = sorted(graph.descendants(root_stage) & failed_stages, key=lambda stage: graph.depth(stage))
    for stage in impacted:
        steps.append(VerificationStep(stage, "targeted", "confirm predicted downstream failure disappears"))
    steps.append(VerificationStep("*", "full-pipeline", "guard against regressions outside the causal path"))
    return steps

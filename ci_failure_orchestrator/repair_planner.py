from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol

from .graph import PipelineGraph
from .models import RankedFailure
from .verification import VerificationStep, plan_verification


@dataclass(frozen=True)
class RepairPlan:
    root_stage: str
    hypothesis: str
    target_files: tuple[str, ...]
    proposed_change: str
    verification: tuple[VerificationStep, ...]
    risk: str
    requires_human_approval: bool
    rollback: str = "revert_patch"
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["verification"] = [step.to_dict() for step in self.verification]
        return result


class RepairPlanner(Protocol):
    def plan(
        self,
        graph: PipelineGraph,
        ranked_failure: RankedFailure,
        failed_stages: set[str],
    ) -> RepairPlan:
        ...


class DeterministicRepairPlanner:
    """Safe baseline planner that turns RCA output into a constrained repair plan.

    This intentionally does not edit code. It produces a bounded plan that a coding
    agent can execute later and an evaluator can independently verify.
    """

    _PLAYBOOKS = {
        "TYPE_ERROR": ("fix the smallest type-contract violation at the failing stage", "low"),
        "TEST_ASSERTION": ("repair the implementation or test assumption causing the failed assertion", "medium"),
        "DEPENDENCY_ERROR": ("restore a compatible dependency or lockfile state", "medium"),
        "BUILD_ERROR": ("repair the smallest build configuration or compile failure", "medium"),
        "LINT_ERROR": ("apply the smallest source change that satisfies the lint rule", "low"),
        "SECURITY_ERROR": ("remediate the security finding without weakening the policy gate", "high"),
        "DEPLOYMENT_ERROR": ("repair deployment configuration only after upstream causes are excluded", "high"),
        "INFRA_ERROR": ("repair or isolate the infrastructure fault before changing application code", "high"),
    }

    def __init__(self, human_approval_risks: set[str] | None = None):
        self.human_approval_risks = human_approval_risks or {"high"}

    def plan(
        self,
        graph: PipelineGraph,
        ranked_failure: RankedFailure,
        failed_stages: set[str],
    ) -> RepairPlan:
        failure = ranked_failure.failure
        proposed_change, risk = self._PLAYBOOKS.get(
            failure.error_type,
            ("inspect the failure evidence and produce the smallest reversible change", "high"),
        )

        target_files = tuple(
            str(path)
            for path in failure.metadata.get("files", [])
            if isinstance(path, (str, bytes))
        )

        verification = tuple(
            plan_verification(graph, failure.stage, failed_stages)
        )

        hypothesis = (
            f"{failure.error_type} at {failure.stage} is the leading root-cause hypothesis "
            f"(rank score={ranked_failure.score:.3f}, confidence={failure.confidence:.2f})"
        )

        return RepairPlan(
            root_stage=failure.stage,
            hypothesis=hypothesis,
            target_files=target_files,
            proposed_change=proposed_change,
            verification=verification,
            risk=risk,
            requires_human_approval=risk in self.human_approval_risks,
            metadata={
                "error_type": failure.error_type,
                "planner": self.__class__.__name__,
            },
        )

"""Repair planning for bounded autonomous CI repair operations.

This module provides the repair planning layer that turns root-cause analysis
output into constrained, auditable repair plans with verification steps and
risk-based human approval requirements.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol

from .graph import PipelineGraph
from .models import RankedFailure
from .verification import VerificationStep, plan_verification


@dataclass(frozen=True)
class RepairPlan:
    """Constrained repair plan for autonomous CI repair operations.

    Attributes:
        root_stage: The root-cause stage where the repair should be applied.
        hypothesis: Human-readable hypothesis explaining the root cause.
        target_files: Tuple of file paths that may be modified (bounded scope).
        proposed_change: Description of the proposed change (not the code itself).
        verification: Tuple of verification steps to validate the repair.
        risk: Risk level (e.g., "low", "medium", "high") for approval gating.
        requires_human_approval: Whether human approval is required before execution.
        rollback: Rollback strategy (default: "revert_patch").
        metadata: Additional context such as error type and planner identifier.

    Audit Notes:
        - Target files bound the scope of what agents may modify.
        - Human approval requirements prevent high-risk autonomous changes.
        - Recovery: Review repair plans and target file scope before approval.
        - Evidence: All repair plans include hypothesis, risk level, and verification steps.
    """

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
        """Convert the repair plan to a dictionary representation.

        Returns:
            Dictionary containing all plan fields with nested verification steps.
        """
        result = asdict(self)
        result["verification"] = [step.to_dict() for step in self.verification]
        return result


class RepairPlanner(Protocol):
    """Protocol for repair planning strategies."""

    def plan(
        self,
        graph: PipelineGraph,
        ranked_failure: RankedFailure,
        failed_stages: set[str],
    ) -> RepairPlan:
        """Generate a repair plan for a ranked failure.

        Args:
            graph: Pipeline dependency graph.
            ranked_failure: Ranked failure with root-cause hypothesis.
            failed_stages: Set of all failed stage IDs.

        Returns:
            RepairPlan with bounded scope, verification steps, and risk assessment.
        """
        ...


class DeterministicRepairPlanner:
    """Safe baseline planner that turns RCA output into a constrained repair plan.

    This planner uses deterministic playbooks for known error types and produces
    bounded plans that coding agents can execute later and evaluators can
    independently verify. It intentionally does not edit code directly.

    Attributes:
        human_approval_risks: Set of risk levels requiring human approval (default: {"high"}).

    Playbooks:
        Each error type maps to a (proposed_change, risk_level) tuple:
        - TYPE_ERROR: fix smallest type-contract violation (low risk)
        - TEST_ASSERTION: repair implementation or test assumption (medium risk)
        - DEPENDENCY_ERROR: restore compatible dependency or lockfile (medium risk)
        - BUILD_ERROR: repair smallest build configuration (medium risk)
        - LINT_ERROR: apply smallest source change for lint rule (low risk)
        - SECURITY_ERROR: remediate without weakening policy (high risk)
        - DEPLOYMENT_ERROR: repair config after excluding upstream causes (high risk)
        - INFRA_ERROR: repair or isolate infra fault before code changes (high risk)
        - UNKNOWN: inspect evidence and produce smallest reversible change (high risk)

    Audit Notes:
        - Playbook-based planning reduces agent autonomy and increases predictability.
        - High-risk error types require human approval by default.
        - Recovery: Review playbook mappings and add new error types as needed.
        - Evidence: All plans include error type, hypothesis, and verification steps.
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
        """Initialize the deterministic repair planner.

        Args:
            human_approval_risks: Set of risk levels requiring human approval.
                Defaults to {"high"} for conservative approval gating.
        """
        self.human_approval_risks = human_approval_risks or {"high"}

    def plan(
        self,
        graph: PipelineGraph,
        ranked_failure: RankedFailure,
        failed_stages: set[str],
    ) -> RepairPlan:
        """Generate a repair plan using deterministic playbooks.

        Args:
            graph: Pipeline dependency graph (used for verification planning).
            ranked_failure: Ranked failure with root-cause hypothesis and metadata.
            failed_stages: Set of all failed stage IDs (used for verification planning).

        Returns:
            RepairPlan with bounded target files, verification steps, and risk assessment.

        Plan Generation:
            1. Look up error type in playbook to get proposed change and risk level.
            2. Extract target files from failure metadata (bounded scope).
            3. Generate verification steps for the affected pipeline stages.
            4. Build hypothesis with rank score and confidence.
            5. Set human approval requirement based on risk level.
        """
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

"""CI Failure Orchestrator."""

__version__ = "1.2.0"

# Bounded agent reliability harness (provider-neutral, fail-closed).
from .model_client import (
    FixtureModelClient,
    StructuredDiagnosis,
    StructuredModelClient,
    validate_and_build_diagnosis,
)
from .repair_proposal import (
    FORBIDDEN_ACTIONS,
    KNOWN_ACTIONS,
    SUPPORTED_ACTIONS,
    RiskClass,
    RepairProposal,
    build_proposal,
    repair_proposal_roundtrip,
    ProposalValidationError,
)
from .proposal_policy import (
    ProposalDisposition,
    ProposalPolicyContext,
    ProposalPolicyGate,
)
from .repair_plan_evaluator import RepairPlanEvaluator, RepairPlanEvaluation
from .escalation import HumanEscalation, build_escalation
from .agent_harness import (
    AgentStep,
    AgentStepTrace,
    AgentRunResult,
    BoundedRepairAgentHarness,
)

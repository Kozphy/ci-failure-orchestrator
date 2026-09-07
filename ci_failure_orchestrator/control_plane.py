from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .evaluator import RetryBudget, next_action


class RunStatus(str, Enum):
    DETECTED = "detected"
    PLANNING = "planning"
    REPAIRING = "repairing"
    EVALUATING = "evaluating"
    AWAITING_APPROVAL = "awaiting_approval"
    DEPLOYING = "deploying"
    VERIFIED = "verified"
    FAILED = "failed"
    ESCALATED = "escalated"


@dataclass
class RepairPlan:
    hypothesis: str
    evidence: list[str]
    steps: list[str]
    risk_score: float
    confidence: float
    estimated_cost_usd: float = 0.0


@dataclass
class AgentRun:
    agent_id: str
    role: str
    status: str = "queued"
    attempts: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    output_ref: str | None = None


@dataclass
class EvaluationResult:
    passed: bool
    score: float
    checks: dict[str, bool]
    regressions: int = 0
    security_findings: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class ApprovalDecision:
    required: bool
    reason: str = ""
    approved: bool | None = None
    reviewer: str | None = None


@dataclass
class ProductionEvidence:
    incident_id: str
    repair_commit: str | None
    tests_passed: int
    regressions: int
    deployment_strategy: str
    rollback_ready: bool
    production_verified: bool
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ControlPlaneRun:
    incident_id: str
    status: RunStatus = RunStatus.DETECTED
    root_cause: str | None = None
    plan: RepairPlan | None = None
    agents: list[AgentRun] = field(default_factory=list)
    evaluation: EvaluationResult | None = None
    approval: ApprovalDecision | None = None
    evidence: ProductionEvidence | None = None
    retry_budget: RetryBudget = field(default_factory=RetryBudget)

    def policy_gate(self) -> str:
        if self.evaluation is None:
            raise ValueError("evaluation is required before policy_gate")

        action = next_action(
            check_passed=self.evaluation.passed,
            budget=self.retry_budget,
            risk_score=self.plan.risk_score if self.plan else 0.0,
        )

        if action == "ESCALATE_HUMAN":
            self.status = RunStatus.ESCALATED
            self.approval = ApprovalDecision(required=True, reason="risk or retry budget exceeded")
        elif action == "RUN_FULL_PIPELINE":
            risky = bool(self.plan and self.plan.risk_score >= 0.6)
            self.approval = ApprovalDecision(required=risky, reason="high-impact change" if risky else "")
            self.status = RunStatus.AWAITING_APPROVAL if risky else RunStatus.DEPLOYING
        else:
            self.status = RunStatus.REPAIRING

        return action

    def telemetry(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "agents": len(self.agents),
            "llm_tokens": sum(a.tokens for a in self.agents),
            "cost_usd": round(sum(a.cost_usd for a in self.agents), 6),
            "latency_ms": sum(a.latency_ms for a in self.agents),
            "retries_used": self.retry_budget.attempts,
            "status": self.status.value,
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

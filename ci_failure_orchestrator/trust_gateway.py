from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .audit import HashChainedAuditLog
from .execution import IsolatedWorkspace
from .trust import ContextRequest, TrustContextBuilder
from .trust_policy import PolicyResult, TrustDecision, TrustPolicyEngine


class GatewayState(str, Enum):
    RECEIVED = "RECEIVED"
    PROPOSED = "PROPOSED"
    CONTEXT_READY = "CONTEXT_READY"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    DENIED = "DENIED"
    SANDBOX_READY = "SANDBOX_READY"
    EXECUTING = "EXECUTING"
    EVALUATING = "EVALUATING"
    VERIFYING = "VERIFYING"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
    SUCCESS = "SUCCESS"


_TRANSITIONS = {
    GatewayState.RECEIVED: {GatewayState.PROPOSED},
    GatewayState.PROPOSED: {GatewayState.CONTEXT_READY, GatewayState.HUMAN_ESCALATION},
    GatewayState.CONTEXT_READY: {GatewayState.POLICY_EVALUATED},
    GatewayState.POLICY_EVALUATED: {
        GatewayState.APPROVAL_PENDING,
        GatewayState.BUDGET_EXHAUSTED,
        GatewayState.DENIED,
        GatewayState.SANDBOX_READY,
    },
    GatewayState.SANDBOX_READY: {GatewayState.EXECUTING},
    GatewayState.EXECUTING: {GatewayState.EVALUATING},
    GatewayState.EVALUATING: {GatewayState.VERIFYING, GatewayState.RETRYABLE_FAILURE},
    GatewayState.VERIFYING: {GatewayState.SUCCESS, GatewayState.RETRYABLE_FAILURE},
    GatewayState.RETRYABLE_FAILURE: {GatewayState.PROPOSED, GatewayState.BUDGET_EXHAUSTED},
    GatewayState.BUDGET_EXHAUSTED: {GatewayState.HUMAN_ESCALATION},
}


class InvalidGatewayTransition(ValueError):
    pass


@dataclass
class GatewayStateMachine:
    state: GatewayState = GatewayState.RECEIVED
    history: list[GatewayState] = field(default_factory=lambda: [GatewayState.RECEIVED])

    def transition(self, target: GatewayState) -> None:
        if target not in _TRANSITIONS.get(self.state, set()):
            raise InvalidGatewayTransition(f"invalid transition: {self.state.value} -> {target.value}")
        self.state = target
        self.history.append(target)


@dataclass(frozen=True)
class RepairProposal:
    proposal_id: str
    problem: str
    tool: str
    operation: str
    arguments: dict[str, Any]
    expected_effect: str
    risk_level: str
    rollback: str
    verification: tuple[dict[str, Any], ...]
    provider: str
    data_classification: str | None
    destination_host: str | None = None
    destructive: bool = False
    package_name: str | None = None
    estimated_cost: float = 0.0
    reason_for_retry: str | None = None
    changed_assumption: str | None = None

    def fingerprint(self) -> str:
        material = {"tool": self.tool, "operation": self.operation, "arguments": self.arguments}
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMClient(Protocol):
    def generate_tool_request(
        self,
        prompt: str,
        *,
        attempt_number: int,
        previous_evaluation: EvaluationResult | None,
    ) -> RepairProposal: ...


class MockLLMClient:
    def __init__(self, proposals: list[RepairProposal]) -> None:
        self.proposals = proposals

    def generate_tool_request(
        self,
        prompt: str,
        *,
        attempt_number: int,
        previous_evaluation: EvaluationResult | None,
    ) -> RepairProposal:
        del prompt, previous_evaluation
        if attempt_number > len(self.proposals):
            raise RuntimeError("mock LLM has no proposal for this attempt")
        return self.proposals[attempt_number - 1]


class OpenAIToolProposalClient:
    """Real OpenAI adapter that emits proposals but has no policy or tool authority."""

    def __init__(self, *, model: str = "gpt-5.6", client: Any = None) -> None:
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - optional integration
                raise RuntimeError("OpenAI integration requires the optional 'openai' dependency") from exc
            client = OpenAI()
        self.client = client
        self.model = model

    def generate_tool_request(
        self,
        prompt: str,
        *,
        attempt_number: int,
        previous_evaluation: EvaluationResult | None,
    ) -> RepairProposal:
        schema = {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string"},
                "problem": {"type": "string"},
                "tool": {"type": "string"},
                "operation": {"type": "string"},
                "arguments_json": {"type": "string"},
                "expected_effect": {"type": "string"},
                "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "rollback": {"type": "string"},
                "verification": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string", "enum": ["file_contains", "file_not_contains"]},
                            "path": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["name", "type", "path", "value"],
                        "additionalProperties": False,
                    },
                },
                "provider": {"type": "string"},
                "data_classification": {"type": ["string", "null"]},
                "destination_host": {"type": ["string", "null"]},
                "destructive": {"type": "boolean"},
                "package_name": {"type": ["string", "null"]},
                "estimated_cost": {"type": "number", "minimum": 0},
                "reason_for_retry": {"type": ["string", "null"]},
                "changed_assumption": {"type": ["string", "null"]},
            },
            "required": [
                "proposal_id", "problem", "tool", "operation", "arguments_json", "expected_effect",
                "risk_level", "rollback", "verification", "provider", "data_classification",
                "destination_host", "destructive", "package_name", "estimated_cost",
                "reason_for_retry", "changed_assumption",
            ],
            "additionalProperties": False,
        }
        prior = previous_evaluation.to_dict() if previous_evaluation else None
        response = self.client.responses.create(
            model=self.model,
            input=(
                "Propose one structured tool action. You do not authorize or execute it. "
                f"Attempt: {attempt_number}. Previous evaluation: {json.dumps(prior)}. Request: {prompt}"
            ),
            text={"format": {"type": "json_schema", "name": "tool_proposal", "schema": schema, "strict": True}},
        )
        payload = json.loads(response.output_text)
        payload["arguments"] = json.loads(payload.pop("arguments_json"))
        payload["verification"] = tuple(payload["verification"])
        return RepairProposal(**payload)


@dataclass(frozen=True)
class ToolExecutionResult:
    command_success: bool
    changed_files: tuple[str, ...]
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolExecutor(Protocol):
    def bind_gateway(self, authority: object) -> None: ...
    def execute(self, proposal: RepairProposal, workspace: Path, *, authority: object) -> ToolExecutionResult: ...


class AllowlistedFileExecutor:
    """A deliberately narrow executor; it can mutate only the disposable workspace."""

    TOOL = "file.repair"

    def __init__(self) -> None:
        self._gateway_authority: object | None = None

    def bind_gateway(self, authority: object) -> None:
        if self._gateway_authority is not None:
            raise RuntimeError("executor is already bound to a gateway")
        self._gateway_authority = authority

    def execute(self, proposal: RepairProposal, workspace: Path, *, authority: object) -> ToolExecutionResult:
        if authority is not self._gateway_authority:
            raise PermissionError("tool execution requires gateway authorization")
        if proposal.tool != self.TOOL:
            raise ValueError(f"unsupported tool: {proposal.tool}")
        relative = Path(str(proposal.arguments["path"]))
        target = (workspace / relative).resolve()
        if workspace.resolve() not in target.parents or not target.is_file():
            raise ValueError("repair target must be an existing file inside the sandbox")
        text = target.read_text(encoding="utf-8")
        strategy = proposal.arguments.get("strategy")
        if strategy == "replace_text":
            old = str(proposal.arguments["old"])
            if old not in text:
                return ToolExecutionResult(False, (), stderr="replacement token not found")
            updated = text.replace(old, str(proposal.arguments["new"]), 1)
        elif strategy == "append_line":
            updated = text + str(proposal.arguments["line"]) + "\n"
        else:
            raise ValueError(f"unsupported file repair strategy: {strategy}")
        target.write_text(updated, encoding="utf-8")
        return ToolExecutionResult(True, (relative.as_posix(),), metadata={"bytes_changed": abs(len(updated) - len(text))})


@dataclass(frozen=True)
class EvaluationResult:
    success: bool
    score: float
    checks: dict[str, bool]
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionEvaluator:
    def evaluate(self, proposal: RepairProposal, result: ToolExecutionResult) -> EvaluationResult:
        checks = {
            "command_success": result.command_success,
            "target_file_changed": bool(result.changed_files),
            "expected_target_changed": str(proposal.arguments.get("path", "")) in result.changed_files,
        }
        success = all(checks.values())
        return EvaluationResult(success, sum(checks.values()) / len(checks), checks, None if success else "execution evidence did not satisfy expected mutation")


class ProposalVerifier:
    def verify(self, proposal: RepairProposal, workspace: Path) -> EvaluationResult:
        checks: dict[str, bool] = {}
        for index, check in enumerate(proposal.verification):
            name = check.get("name", f"check_{index + 1}")
            kind = check.get("type")
            target = (workspace / str(check.get("path", ""))).resolve()
            within_workspace = workspace.resolve() in target.parents
            if kind == "file_contains" and within_workspace and target.is_file():
                checks[name] = str(check.get("value", "")) in target.read_text(encoding="utf-8")
            elif kind == "file_not_contains" and within_workspace and target.is_file():
                checks[name] = str(check.get("value", "")) not in target.read_text(encoding="utf-8")
            else:
                checks[name] = False
        success = bool(checks) and all(checks.values())
        score = sum(checks.values()) / len(checks) if checks else 0.0
        return EvaluationResult(success, score, checks, None if success else "target-condition verification failed")


@dataclass
class RetryBudget:
    max_attempts: int = 3
    max_total_cost: float = 1.0
    max_wall_time: float = 60.0
    attempts: int = 0
    total_cost: float = 0.0
    started_at: float = field(default_factory=time.monotonic)

    def consume(self, cost: float) -> bool:
        if cost < 0:
            raise ValueError("estimated cost must be non-negative")
        if self.attempts >= self.max_attempts or self.total_cost + cost > self.max_total_cost:
            return False
        if time.monotonic() - self.started_at > self.max_wall_time:
            return False
        self.attempts += 1
        self.total_cost += cost
        return True

    def remaining(self) -> dict[str, Any]:
        return {
            "attempts": max(self.max_attempts - self.attempts, 0),
            "cost": max(self.max_total_cost - self.total_cost, 0.0),
            "wall_time": max(self.max_wall_time - (time.monotonic() - self.started_at), 0.0),
        }


@dataclass(frozen=True)
class AttemptRecord:
    attempt_number: int
    proposal: dict[str, Any]
    reason_for_retry: str | None
    changed_assumption: str | None
    policy: dict[str, Any]
    evaluation: dict[str, Any] | None
    verification: dict[str, Any] | None
    remaining_budget: dict[str, Any]


@dataclass(frozen=True)
class GatewayResult:
    status: str
    correlation_id: str
    policy_decision: dict[str, Any]
    attempts: tuple[AttemptRecord, ...]
    state_history: tuple[str, ...]
    escalation: dict[str, Any] | None = None


class TrustToolGateway:
    METRIC_NAMES = (
        "policy_allow_count",
        "policy_deny_count",
        "approval_required_count",
        "tool_execution_count",
        "tool_failure_count",
        "retry_count",
        "retry_exhaustion_count",
        "human_escalation_count",
        "verified_success_count",
    )

    def __init__(
        self,
        *,
        llm: LLMClient,
        context_builder: TrustContextBuilder,
        policy: TrustPolicyEngine,
        executor: ToolExecutor,
        evaluator: ExecutionEvaluator,
        verifier: ProposalVerifier,
        audit: HashChainedAuditLog,
        source_workspace: str | Path,
        retry_budget: RetryBudget | None = None,
    ) -> None:
        self.llm = llm
        self.context_builder = context_builder
        self.policy = policy
        self.executor = executor
        self._execution_authority = object()
        self.executor.bind_gateway(self._execution_authority)
        self.evaluator = evaluator
        self.verifier = verifier
        self.audit = audit
        self.source_workspace = Path(source_workspace)
        self.retry_budget = retry_budget or RetryBudget()
        self.metrics: Counter[str] = Counter()

    def metrics_snapshot(self) -> dict[str, int]:
        return {name: self.metrics[name] for name in self.METRIC_NAMES}

    def run(self, prompt: str, *, human_approved: bool = False) -> GatewayResult:
        correlation_id = str(uuid.uuid4())
        state = GatewayStateMachine()
        attempts: list[AttemptRecord] = []
        fingerprints: set[str] = set()
        previous_evaluation: EvaluationResult | None = None
        last_policy: PolicyResult | None = None
        self._event(correlation_id, "request_received", {"prompt": "[OMITTED]"})

        while True:
            attempt_number = self.retry_budget.attempts + 1
            proposal = self.llm.generate_tool_request(
                prompt,
                attempt_number=attempt_number,
                previous_evaluation=previous_evaluation,
            )
            state.transition(GatewayState.PROPOSED)
            self._event(correlation_id, "llm_proposal", proposal.to_dict())
            if attempt_number > 1 and (not proposal.reason_for_retry or not proposal.changed_assumption):
                state.transition(GatewayState.HUMAN_ESCALATION)
                self.metrics["human_escalation_count"] += 1
                packet = self._escalation("retry proposal lacks failure rationale or changed assumption", proposal, last_policy, attempts)
                self._event(correlation_id, "human_escalation", packet)
                return self._result("human_review_required", correlation_id, last_policy, attempts, state, packet)
            fingerprint = proposal.fingerprint()
            if fingerprint in fingerprints:
                state.transition(GatewayState.HUMAN_ESCALATION)
                self.metrics["human_escalation_count"] += 1
                packet = self._escalation("identical failing action proposed without new evidence", proposal, last_policy, attempts)
                self._event(correlation_id, "human_escalation", packet)
                return self._result("human_review_required", correlation_id, last_policy, attempts, state, packet)
            fingerprints.add(fingerprint)

            context = self.context_builder.build(
                ContextRequest(
                    provider=proposal.provider,
                    tool=proposal.tool,
                    operation=proposal.operation,
                    data_classification=proposal.data_classification,
                    destination_host=proposal.destination_host,
                    destructive=proposal.destructive,
                    package_name=proposal.package_name,
                    human_approved=human_approved,
                )
            )
            state.transition(GatewayState.CONTEXT_READY)
            self._event(correlation_id, "context_created", context.to_dict())
            self._event(correlation_id, "network_probe", context.network_capabilities)
            last_policy = self.policy.evaluate(context)
            state.transition(GatewayState.POLICY_EVALUATED)
            self._event(correlation_id, "policy_decision", last_policy.to_dict())

            if last_policy.decision is TrustDecision.DENY:
                state.transition(GatewayState.DENIED)
                self.metrics["policy_deny_count"] += 1
                return self._result("denied", correlation_id, last_policy, attempts, state)
            if last_policy.decision is TrustDecision.REQUIRE_APPROVAL:
                state.transition(GatewayState.APPROVAL_PENDING)
                self.metrics["approval_required_count"] += 1
                self._event(correlation_id, "approval_requested", {"proposal_id": proposal.proposal_id, "policy": last_policy.to_dict()})
                return self._result("approval_required", correlation_id, last_policy, attempts, state)

            self.metrics["policy_allow_count"] += 1
            if human_approved and last_policy.rule_id.endswith("_APPROVED"):
                self._event(correlation_id, "approval_received", {"proposal_id": proposal.proposal_id})
            if not self.retry_budget.consume(proposal.estimated_cost):
                state.transition(GatewayState.BUDGET_EXHAUSTED)
                state.transition(GatewayState.HUMAN_ESCALATION)
                self.metrics["retry_exhaustion_count"] += 1
                self.metrics["human_escalation_count"] += 1
                packet = self._escalation("retry budget exhausted before execution", proposal, last_policy, attempts)
                self._event(correlation_id, "retry_budget_exhausted", self.retry_budget.remaining())
                self._event(correlation_id, "human_escalation", packet)
                return self._result("human_review_required", correlation_id, last_policy, attempts, state, packet)

            state.transition(GatewayState.SANDBOX_READY)
            with IsolatedWorkspace(self.source_workspace) as sandbox:
                assert sandbox.path is not None
                state.transition(GatewayState.EXECUTING)
                try:
                    execution = self.executor.execute(proposal, sandbox.path, authority=self._execution_authority)
                except (KeyError, OSError, ValueError) as exc:
                    execution = ToolExecutionResult(
                        command_success=False,
                        changed_files=(),
                        stderr=f"{type(exc).__name__}: {exc}",
                    )
                self.metrics["tool_execution_count"] += 1
                self._event(correlation_id, "sandbox_execution", asdict(execution))
                state.transition(GatewayState.EVALUATING)
                evaluation = self.evaluator.evaluate(proposal, execution)
                self._event(correlation_id, "evaluation_result", evaluation.to_dict())
                verification: EvaluationResult | None = None
                if evaluation.success:
                    state.transition(GatewayState.VERIFYING)
                    verification = self.verifier.verify(proposal, sandbox.path)
                    self._event(correlation_id, "verification_result", verification.to_dict())
                    if verification.success:
                        state.transition(GatewayState.SUCCESS)
                        self.metrics["verified_success_count"] += 1
                        record = self._attempt(attempt_number, proposal, last_policy, evaluation, verification)
                        attempts.append(record)
                        self._event(correlation_id, "workflow_completed", {"status": "verified_success"})
                        return self._result("verified_success", correlation_id, last_policy, attempts, state)
                self.metrics["tool_failure_count"] += 1
                previous_evaluation = verification or evaluation
                state.transition(GatewayState.RETRYABLE_FAILURE)
                attempts.append(self._attempt(attempt_number, proposal, last_policy, evaluation, verification))

            if self.retry_budget.attempts >= self.retry_budget.max_attempts:
                state.transition(GatewayState.BUDGET_EXHAUSTED)
                state.transition(GatewayState.HUMAN_ESCALATION)
                self.metrics["retry_exhaustion_count"] += 1
                self.metrics["human_escalation_count"] += 1
                packet = self._escalation(previous_evaluation.failure_reason or "verification failed", proposal, last_policy, attempts)
                self._event(correlation_id, "retry_budget_exhausted", self.retry_budget.remaining())
                self._event(correlation_id, "human_escalation", packet)
                return self._result("human_review_required", correlation_id, last_policy, attempts, state, packet)
            self.metrics["retry_count"] += 1
            self._event(
                correlation_id,
                "retry_scheduled",
                {"attempt_number": attempt_number + 1, "failure_reason": previous_evaluation.failure_reason, "remaining_budget": self.retry_budget.remaining()},
            )

    def _attempt(self, number: int, proposal: RepairProposal, policy: PolicyResult, evaluation: EvaluationResult | None, verification: EvaluationResult | None) -> AttemptRecord:
        return AttemptRecord(number, proposal.to_dict(), proposal.reason_for_retry, proposal.changed_assumption, policy.to_dict(), evaluation.to_dict() if evaluation else None, verification.to_dict() if verification else None, self.retry_budget.remaining())

    def _event(self, correlation_id: str, event: str, payload: dict[str, Any]) -> None:
        self.audit.append(event, payload, correlation_id=correlation_id)

    @staticmethod
    def _escalation(reason: str, proposal: RepairProposal, policy: PolicyResult | None, attempts: list[AttemptRecord]) -> dict[str, Any]:
        return {
            "status": "human_review_required",
            "reason": reason,
            "proposed_action": proposal.to_dict(),
            "policy_decision": policy.to_dict() if policy else {},
            "attempts": [asdict(item) for item in attempts],
            "evidence": ["correlated append-only audit trail"],
            "recommended_next_actions": ["Review the failed checks and changed assumption", "Approve a materially different bounded proposal or stop the workflow"],
            "approval_effect": "Approval permits only the identified proposal to enter sandbox execution; verification remains mandatory.",
        }

    @staticmethod
    def _result(status: str, correlation_id: str, policy: PolicyResult | None, attempts: list[AttemptRecord], state: GatewayStateMachine, escalation: dict[str, Any] | None = None) -> GatewayResult:
        return GatewayResult(status, correlation_id, policy.to_dict() if policy else {}, tuple(attempts), tuple(item.value for item in state.history), escalation)

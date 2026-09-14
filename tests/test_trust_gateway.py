import json
from itertools import pairwise
from pathlib import Path

import pytest

from ci_failure_orchestrator.audit import HashChainedAuditLog
from ci_failure_orchestrator.provenance import DependencyProvenanceEvaluator
from ci_failure_orchestrator.trust import ProviderRegistry, TrustContextBuilder
from ci_failure_orchestrator.trust_gateway import (
    AllowlistedFileExecutor,
    ExecutionEvaluator,
    GatewayState,
    GatewayStateMachine,
    InvalidGatewayTransition,
    MockLLMClient,
    OpenAIToolProposalClient,
    ProposalVerifier,
    RepairProposal,
    RetryBudget,
    TrustToolGateway,
)
from ci_failure_orchestrator.trust_policy import TrustPolicyEngine

ROOT = Path(__file__).resolve().parent.parent


class StaticNetwork:
    def discover(self, host):
        return {"host": host, "dns": "pass", "ipv4": "pass", "ipv6": "fail", "tcp": "pass", "tcp_443": "pass", "tls": "pass", "http": "pass", "authentication": "not_required_or_pass"}


def proposal(identifier, *, strategy="append_line", value="NOPE", provider="local_ollama", classification="CONFIDENTIAL", destructive=False, retry=False):
    arguments = {"path": "value.txt", "strategy": strategy}
    if strategy == "append_line":
        arguments["line"] = value
    else:
        arguments.update(old="BROKEN", new=value)
    return RepairProposal(
        proposal_id=identifier,
        problem="broken marker",
        tool="file.repair",
        operation="delete" if destructive else "write",
        arguments=arguments,
        expected_effect="value is fixed",
        risk_level="high" if destructive else "low",
        rollback="discard sandbox",
        verification=({"name": "fixed", "type": "file_contains", "path": "value.txt", "value": "FIXED"},),
        provider=provider,
        data_classification=classification,
        destructive=destructive,
        estimated_cost=0.1,
        reason_for_retry="target condition remained false" if retry else None,
        changed_assumption="replace the marker instead of appending" if retry else None,
    )


def gateway(tmp_path, proposals, *, max_attempts=3, executor=None):
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    (source / "value.txt").write_text("BROKEN\n", encoding="utf-8")
    audit_path = tmp_path / "audit.jsonl"
    instance = TrustToolGateway(
        llm=MockLLMClient(proposals),
        context_builder=TrustContextBuilder(
            ProviderRegistry.from_file(ROOT / "config/providers.yaml"),
            StaticNetwork(),
            DependencyProvenanceEvaluator(ROOT),
        ),
        policy=TrustPolicyEngine.from_file(ROOT / "config/policies.yaml"),
        executor=executor or AllowlistedFileExecutor(),
        evaluator=ExecutionEvaluator(),
        verifier=ProposalVerifier(),
        audit=HashChainedAuditLog(audit_path),
        source_workspace=source,
        retry_budget=RetryBudget(max_attempts=max_attempts, max_total_cost=1, max_wall_time=30),
    )
    return instance, source, audit_path


def events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_end_to_end_retry_changes_action_then_verifies(tmp_path):
    first = proposal("p1")
    second = proposal("p2", strategy="replace_text", value="FIXED", retry=True)
    instance, source, audit_path = gateway(tmp_path, [first, second])
    result = instance.run("repair it")
    assert result.status == "verified_success"
    assert len(result.attempts) == 2
    assert (source / "value.txt").read_text(encoding="utf-8") == "BROKEN\n"
    names = [item["event"] for item in events(audit_path)]
    assert names.count("policy_decision") == 2
    assert names.index("evaluation_result") < names.index("verification_result") < names.index("retry_scheduled")
    assert names[-1] == "workflow_completed"
    assert instance.metrics["retry_count"] == 1
    assert instance.metrics["verified_success_count"] == 1


def test_destructive_external_action_pauses_before_execution(tmp_path):
    instance, _, audit_path = gateway(tmp_path, [proposal("danger", provider="openai", classification="PUBLIC", destructive=True)])
    result = instance.run("delete")
    assert result.status == "approval_required"
    assert result.policy_decision["rule_id"] == "DESTRUCTIVE_ACTION"
    assert "sandbox_execution" not in [item["event"] for item in events(audit_path)]
    assert instance.metrics["tool_execution_count"] == 0


def test_unknown_provider_destructive_action_is_denied_before_execution(tmp_path):
    instance, _, audit_path = gateway(tmp_path, [proposal("denied", provider="unknown", destructive=True)])
    result = instance.run("delete")
    assert result.status == "denied"
    assert result.policy_decision["rule_id"] == "UNKNOWN_PROVIDER_DESTRUCTIVE"
    assert "sandbox_execution" not in [item["event"] for item in events(audit_path)]


def test_human_approval_is_recorded_before_protected_execution(tmp_path):
    action = proposal("danger-approved", provider="openai", classification="PUBLIC", destructive=True, strategy="replace_text", value="FIXED")
    instance, _, audit_path = gateway(tmp_path, [action])
    assert instance.run("delete", human_approved=True).status == "verified_success"
    names = [item["event"] for item in events(audit_path)]
    assert names.index("approval_received") < names.index("sandbox_execution")


def test_retry_budget_exhaustion_produces_decision_packet(tmp_path):
    instance, _, audit_path = gateway(tmp_path, [proposal("p1")], max_attempts=1)
    result = instance.run("repair")
    assert result.status == "human_review_required"
    assert result.escalation["attempts"]
    assert "recommended_next_actions" in result.escalation
    assert "retry_budget_exhausted" in [item["event"] for item in events(audit_path)]


def test_identical_failed_action_cannot_loop(tmp_path):
    first = proposal("p1")
    second = proposal("p2", retry=True)
    instance, _, _ = gateway(tmp_path, [first, second])
    result = instance.run("repair")
    assert result.status == "human_review_required"
    assert "identical failing action" in result.escalation["reason"]
    assert instance.metrics["tool_execution_count"] == 1


def test_builtin_executor_rejects_gateway_bypass(tmp_path):
    executor = AllowlistedFileExecutor()
    with pytest.raises(PermissionError):
        executor.execute(proposal("p1"), tmp_path, authority=object())


def test_audit_redacts_secrets_and_preserves_correlation(tmp_path):
    action = proposal("token=super-secret", strategy="replace_text", value="FIXED")
    instance, _, audit_path = gateway(tmp_path, [action])
    result = instance.run("Authorization: Bearer should-not-log")
    records = events(audit_path)
    serialized = json.dumps(records)
    assert "super-secret" not in serialized
    assert "should-not-log" not in serialized
    assert {record["correlation_id"] for record in records} == {result.correlation_id}
    for previous, current in pairwise(records):
        assert current["prev_hash"] == previous["hash"]


def test_illegal_state_transition_fails():
    machine = GatewayStateMachine()
    with pytest.raises(InvalidGatewayTransition):
        machine.transition(GatewayState.SUCCESS)


def test_real_provider_adapter_emits_proposal_only():
    payload = proposal("real", strategy="replace_text", value="FIXED").to_dict()
    payload["arguments_json"] = json.dumps(payload.pop("arguments"))
    payload["verification"] = list(payload["verification"])

    class Responses:
        def create(self, **kwargs):
            assert kwargs["text"]["format"]["strict"] is True
            return type("Response", (), {"output_text": json.dumps(payload)})()

    client = type("Client", (), {"responses": Responses()})()
    result = OpenAIToolProposalClient(client=client).generate_tool_request(
        "repair", attempt_number=1, previous_evaluation=None
    )
    assert result.tool == "file.repair"
    assert result.arguments["strategy"] == "replace_text"

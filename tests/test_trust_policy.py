from pathlib import Path

import pytest

from ci_failure_orchestrator.trust import (
    ContextRequest,
    DataClassification,
    ProviderRegistry,
    TrustContextBuilder,
)
from ci_failure_orchestrator.trust_policy import TrustDecision, TrustPolicyEngine

ROOT = Path(__file__).resolve().parent.parent


class StaticNetwork:
    def __init__(self, ready=True):
        status = "pass" if ready else "fail"
        self.evidence = {"dns": status, "ipv4": status, "ipv6": "fail", "tcp": status, "tls": status, "http": status}

    def discover(self, host):
        return {"host": host, **self.evidence}


class StaticProvenance:
    def evaluate(self, package):
        return {"package_name": package, "status": "available"}


def decision(**overrides):
    values = {
        "provider": "openai",
        "tool": "file.repair",
        "operation": "read",
        "data_classification": "PUBLIC",
        "destination_host": "api.openai.com",
    }
    values.update(overrides)
    builder = TrustContextBuilder(
        ProviderRegistry.from_file(ROOT / "config/providers.yaml"),
        StaticNetwork(),
        StaticProvenance(),
    )
    context = builder.build(ContextRequest(**values))
    return TrustPolicyEngine.from_file(ROOT / "config/policies.yaml").evaluate(context)


def test_public_external_provider_is_allowed():
    assert decision().decision is TrustDecision.ALLOW


def test_restricted_external_provider_requires_approval():
    result = decision(data_classification="RESTRICTED")
    assert result.decision is TrustDecision.REQUIRE_APPROVAL
    assert result.rule_id == "RESTRICTED_EXTERNAL_PROVIDER"


def test_confidential_local_provider_is_allowed():
    result = decision(provider="local_ollama", destination_host=None, data_classification="CONFIDENTIAL")
    assert result.decision is TrustDecision.ALLOW
    assert result.rule_id == "CONFIDENTIAL_LOCAL"


def test_unknown_provider_destructive_write_is_denied():
    result = decision(provider="unregistered", operation="delete", destructive=True)
    assert result.decision is TrustDecision.DENY
    assert result.rule_id == "UNKNOWN_PROVIDER_DESTRUCTIVE"


def test_destructive_known_provider_requires_approval():
    assert decision(operation="delete", destructive=True).decision is TrustDecision.REQUIRE_APPROVAL


def test_destructive_operation_cannot_be_downgraded_by_proposal_flag():
    result = decision(operation="delete", destructive=False)
    assert result.decision is TrustDecision.REQUIRE_APPROVAL
    assert result.evidence["destructive"] is True


def test_unknown_classification_is_not_silently_downgraded():
    result = decision(operation="write", data_classification=None)
    assert result.decision is TrustDecision.REQUIRE_APPROVAL
    assert result.evidence["classification"] == "UNKNOWN"
    with pytest.raises(ValueError):
        DataClassification.parse("secret-ish")


def test_jurisdiction_and_residency_mismatch_participate_in_policy():
    builder = TrustContextBuilder(ProviderRegistry.from_file(ROOT / "config/providers.yaml"), StaticNetwork(), StaticProvenance())
    context = builder.build(ContextRequest(
        provider="openai", tool="file.repair", operation="read", data_classification="CONFIDENTIAL",
        data_residency="EU", destination_country="US", destination_host="api.openai.com",
    ))
    result = TrustPolicyEngine.from_file(ROOT / "config/policies.yaml").evaluate(context)
    assert result.rule_id == "DATA_RESIDENCY_MISMATCH"
    assert result.evidence["jurisdictions"] == ("US",)


def test_external_network_evidence_participates_in_policy():
    builder = TrustContextBuilder(ProviderRegistry.from_file(ROOT / "config/providers.yaml"), StaticNetwork(False), StaticProvenance())
    context = builder.build(ContextRequest(provider="openai", tool="file.repair", operation="read", data_classification="PUBLIC"))
    result = TrustPolicyEngine.from_file(ROOT / "config/policies.yaml").evaluate(context)
    assert result.rule_id == "EXTERNAL_NETWORK_UNVERIFIED"

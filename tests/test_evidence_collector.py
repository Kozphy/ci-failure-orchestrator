from ci_failure_orchestrator.evidence_collector import collect_evidence


def test_collects_independent_fragments_without_inventing_gates():
    result = collect_evidence(
        [
            {"tests": {"unit": "pass", "integration": "pass"}},
            {"security": {"secrets_scan": "pass"}},
            {"governance": {"pr_linked": True}},
        ]
    )

    assert result.valid is True
    assert result.evidence == {
        "tests": {"unit": "pass", "integration": "pass"},
        "security": {"secrets_scan": "pass"},
        "governance": {"pr_linked": True},
    }
    assert "docs" not in result.evidence


def test_same_claim_from_multiple_producers_is_allowed():
    result = collect_evidence(
        [
            {"ci": {"required_checks": "pass"}},
            {"ci": {"required_checks": "pass", "policy_gate": "pass"}},
        ]
    )

    assert result.valid is True
    assert result.evidence["ci"] == {
        "required_checks": "pass",
        "policy_gate": "pass",
    }


def test_conflicting_claims_fail_collection_without_overwrite():
    result = collect_evidence(
        [
            {"security": {"vulnerability_scan": "pass"}},
            {"security": {"vulnerability_scan": "fail"}},
        ]
    )

    assert result.valid is False
    assert result.evidence["security"]["vulnerability_scan"] == "pass"
    assert result.conflicts[0].path == "security.vulnerability_scan"
    assert result.conflicts[0].existing == "pass"
    assert result.conflicts[0].incoming == "fail"


def test_nested_fragment_merge_preserves_all_independent_claims():
    result = collect_evidence(
        [
            {"docs": {"public_api": "updated"}},
            {"docs": {"architecture": "updated"}},
            {"docs": {"safety": "updated"}},
        ]
    )

    assert result.valid is True
    assert result.evidence["docs"] == {
        "public_api": "updated",
        "architecture": "updated",
        "safety": "updated",
    }

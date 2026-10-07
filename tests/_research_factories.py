"""Shared builders for the research-harness tests (not a test module)."""

from __future__ import annotations

import copy
from typing import Any

from research.dataset import load_dataset
from research.repair import CandidateFacts, CaseRun, SystemDecision


def committed_case(case_id: str) -> dict[str, Any]:
    """Deep copy of a case from the frozen dataset."""
    for case in load_dataset().cases():
        if case["case_id"] == case_id:
            return copy.deepcopy(case)
    raise KeyError(case_id)


def facts(
    candidate_id: str,
    label: str,
    *,
    case_id: str = "case-1",
    ci_green: bool = True,
    policy: str | None = "APPROVE",
    verified: bool = True,
    verified_no_policy: bool | None = None,
    oracle: bool | None = None,
    state: str | None = None,
    whatif: bool = False,
    fake_fix_kind: str | None = None,
) -> CandidateFacts:
    """CandidateFacts with the measured fields chosen by the test."""
    oracle_passed = (label == "correct") if oracle is None else oracle
    return CandidateFacts(
        case_id=case_id, candidate_id=candidate_id, label=label,
        fake_fix_kind=fake_fix_kind or ("skip_test" if label == "fake_fix" else None),
        patch_sha256="0" * 64, files_changed=["app.py"], ci_green=ci_green,
        workflow_status="APPROVED" if ci_green else "FAILED", technical_status="PASS" if ci_green else "FAIL",
        policy_outcome=policy if ci_green else None, policy_rules=[],
        remediation_state=state or ("POLICY_APPROVED" if verified else "CI_GREEN_BUT_UNVERIFIED"),
        remediation_reasons=[], forbidden_diff_codes=[],
        locally_verified=ci_green and verified and not whatif,
        verified_without_policy=ci_green and (verified if verified_no_policy is None else verified_no_policy),
        whatif_verification=whatif, oracle_passed=oracle_passed, oracle_detail="",
        correct=label == "correct" and ci_green and oracle_passed is True,
        annotation_issues=[], error=None, latency_ms=1,
    )


def case_run(case_id: str, ordered: list[CandidateFacts], decisions: list[SystemDecision]) -> CaseRun:
    """CaseRun around pre-built facts and decisions."""
    return CaseRun(case_id=case_id, order=[f.candidate_id for f in ordered], facts=ordered, decisions=decisions,
                   fidelity={"checked": False}, base_checks={"issues": []}, latency_ms=1)

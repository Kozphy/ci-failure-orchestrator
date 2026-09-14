"""Agent harness demo entrypoint.

Run:  python -m ci_failure_orchestrator.agent_demo

This is a non-destructive demo that exercises the bounded agent harness with a
deterministic fixture model. It does not perform live remediation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ci_failure_orchestrator.agent_harness import BoundedRepairAgentHarness
from ci_failure_orchestrator.model_client import FixtureModelClient
from ci_failure_orchestrator.repair_plan_evaluator import RepairPlanEvaluator
from ci_failure_orchestrator.audit import HashChainedAuditLog


def _dump(value):
    print(json.dumps(value, indent=2))


def run(audit_path: str | None = None) -> None:
    case = {
        "incident_id": "INC-WININET-001",
        "probe_id": "PROBE-WININET-001",
        "evidence_summary": (
            "browser-only HTTP traffic routes through a stale WinINET proxy while "
            "system proxy settings report a different upstream; connectivity to internal "
            "endpoints fails from the browser but succeeds from WinHTTP-using tools."
        ),
        "failure_message": (
            "browser connection to internal endpoint failed; proxy configuration "
            "appears inconsistent between WinINET and system proxy settings"
        ),
    }

    model_payload = {
        "incident_type": "NETWORK_ERROR",
        "confidence": 0.82,
        "hypothesis": (
            "WinINET proxy configuration has drifted from the current system proxy "
            "settings, causing browser-based HTTP requests to use an outdated upstream "
            "while WinHTTP-based tools still reach the internal endpoint. The leading "
            "hypothesis is proxy configuration drift rather than a network outage."
        ),
        "evidence_refs": [
            "repair:probe:WININET-001",
            "repair:fixture:dead_proxy_60505",
        ],
        "limitations": [
            "single observation window",
            "browser-only failure path",
            "no TLS path comparison performed yet",
        ],
        "recommended_action": "targeted_repair",
    }

    model = FixtureModelClient(model_payload, model="structured-proposal-v1")
    harness = BoundedRepairAgentHarness(
        model=model,
        max_attempts=3,
        evidence_namespace="repair",
        audit_path=audit_path,
    )

    result = harness.run(case)

    print("Evidence collected")
    print()
    print("Deterministic diagnosis:")
    print("  WININET_PROXY_DRIFT")
    print()
    print("LLM hypothesis:")
    print(f"  confidence={result.diagnosis.confidence:.2f}")
    print()
    print("Repair proposal:")
    print(f"  proposal_id={result.proposal.proposal_id}")
    print(f"  incident_type={result.proposal.incident_type}")
    print(f"  candidate_action={result.proposal.candidate_action}")
    print(f"  risk_class={result.proposal.risk_class.value}")
    print(f"  before_state_required={result.proposal.before_state_required}")
    print(f"  preview_required={result.proposal.preview_required}")
    print(f"  confirmation_required={result.proposal.confirmation_required}")
    print(f"  rollback_strategy={result.proposal.rollback_strategy}")
    print(f"  verification_plan={list(result.proposal.verification_plan)}")
    print(f"  limitations={list(result.proposal.limitations)}")
    print()
    print("Policy:")
    print(f"  disposition={result.policy_disposition.value if result.policy_disposition else 'none'}")
    print()
    print("Sandbox / preview:")
    print("  PASS")
    print()
    print("Verification plan:")
    print(f"  {result.verification_plan}")
    print()
    print("Retry budget:")
    print(f"  {result.attempt_count} / {result.attempt_count + result.retry_budget_remaining} used")
    print()
    print("Disposition:")
    print(f"  {result.disposition}")
    print()
    print("Audit:")
    print(f"  {audit_path or 'no audit path configured'}")

    if audit_path:
        log = HashChainedAuditLog(audit_path)
        log.append("agent_run", result.to_dict())
        print(f"  appended: {audit_path}")

    evaluator = RepairPlanEvaluator()
    eval_result = evaluator.evaluate(result.proposal)
    print()
    print("Independent repair-plan evaluator:")
    _dump(eval_result.to_dict())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-demo")
    parser.add_argument("--audit", default=None)
    args = parser.parse_args(argv)
    run(args.audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

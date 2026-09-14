from __future__ import annotations
import argparse
import json
from pathlib import Path
from .audit import HashChainedAuditLog
from .classifier import classify_error
from .config import load_failures, load_pipeline
from .graph import PipelineGraph
from .ranker import RootCauseRanker
from .causal import infer_causal_edges
from .verification import plan_verification
from .github_ingest import stages_from_jobs, failures_from_jobs
from .agent_harness import BoundedRepairAgentHarness, FixtureModelClient
from .repair_plan_evaluator import RepairPlanEvaluator
from .model_client import validate_and_build_diagnosis


def _dump(value):
    print(json.dumps(value, indent=2))


def cmd_classify(args):
    error_type, confidence = classify_error(args.message)
    _dump({"error_type": error_type, "confidence": confidence})
    return 0


def cmd_rank(args):
    graph = PipelineGraph(load_pipeline(args.pipeline))
    ranked = RootCauseRanker(graph).rank(load_failures(args.failures))
    output = [item.to_dict() for item in ranked]
    _dump(output)
    if args.audit:
        HashChainedAuditLog(args.audit).append("root_cause_ranked", {"ranking": output})
    return 0


def cmd_analyze(args):
    raw = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
    jobs = raw.get("jobs", raw) if isinstance(raw, dict) else raw
    logs = json.loads(Path(args.logs).read_text(encoding="utf-8")) if args.logs else {}
    stages = stages_from_jobs(jobs)
    failures = failures_from_jobs(jobs, logs)
    graph = PipelineGraph(stages)
    ranked = RootCauseRanker(graph).rank(failures)
    edges = infer_causal_edges(graph, failures)
    root = ranked[0].failure.stage if ranked else None
    plan = plan_verification(graph, root, {f.stage for f in failures}) if root else []
    result = {"root_cause": root, "ranking": [r.to_dict() for r in ranked], "causal_edges": [e.to_dict() for e in edges], "verification_plan": [s.to_dict() for s in plan]}
    _dump(result)
    if args.audit:
        HashChainedAuditLog(args.audit).append("github_actions_analyzed", result)
    return 0


def cmd_agent_demo(args):
    from .agent_harness import BoundedRepairAgentHarness, FixtureModelClient
    from .repair_plan_evaluator import RepairPlanEvaluator
    from .audit import HashChainedAuditLog

    case = {
        "incident_id": "INC-WININET-001",
        "probe_id": "PROBE-WININET-001",
        "evidence_summary": "browser-only HTTP traffic routes through a stale WinINET proxy while system proxy settings report a different upstream; connectivity to internal endpoints fails from the browser but succeeds from WinHTTP-using tools.",
        "failure_message": "browser connection to internal endpoint failed; proxy configuration appears inconsistent between WinINET and system proxy settings",
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
        audit_path=args.audit,
    )
    result = harness.run(case)

    print("Evidence collected")
    print()
    print("Deterministic classification: demonstrate deterministic classifier alongside LLM path")
    _dump({"error_type": "NETWORK_ERROR", "confidence": 0.9})

    print()
    print("LLM hypothesis:")
    if result.diagnosis:
        print(f"  incident_type={result.diagnosis.incident_type}")
        print(f"  confidence={result.diagnosis.confidence:.2f}")
        print(f"  hypothesis={result.diagnosis.hypothesis}")
        print(f"  evidence_refs={list(result.diagnosis.evidence_refs)}")
        print(f"  limitations={list(result.diagnosis.limitations)}")
        print(f"  human_review_required={result.diagnosis.human_review_required}")

    print()
    print("Repair proposal:")
    if result.proposal:
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
        print(f"  human_review_required={result.proposal.human_review_required}")

    print()
    print("Policy:")
    print(f"  disposition={result.policy_disposition.value if result.policy_disposition else None}")

    print()
    print("Sandbox / preview:")
    print("  PASS (demo stops before any live mutation)")

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
    if result.escalation:
        print("Human escalation:")
        print(f"  policy_reason={result.escalation.policy_reason}")
        print(f"  recommended_human_action={result.escalation.recommended_human_action}")
        print(f"  risk_level={result.escalation.risk_level}")
        print(f"  human_review_required={result.escalation.human_review_required}")
    else:
        print("Human escalation: not required for this run")

    print()
    print("Audit:")
    print(f"  {args.audit or 'no audit path configured'}")

    if args.audit:
        log = HashChainedAuditLog(args.audit)
        log.append("agent_run", result.to_dict())
        print(f"  appended: {args.audit}")

    evaluator = RepairPlanEvaluator()
    eval_result = evaluator.evaluate(result.proposal)
    print()
    print("Independent repair-plan evaluator:")
    _dump(eval_result.to_dict())

    return 0


def cmd_agent_eval(args):
    from .model_client import validate_and_build_diagnosis, FixtureModelClient
    from .repair_proposal import build_proposal, ProposalValidationError, FORBIDDEN_ACTIONS, SUPPORTED_ACTIONS
    from .repair_plan_evaluator import RepairPlanEvaluator
    from .escalation import build_escalation
    from .audit import HashChainedAuditLog
    from .policy import PolicyEngine, PolicyContext
    from .models import Failure

    cases = {
        "valid_structured_output": {
            "payload": {
                "incident_type": "NETWORK_ERROR",
                "confidence": 0.82,
                "hypothesis": "proxy drift",
                "evidence_refs": ["repair:probe:WININET-001"],
                "limitations": ["single observation window"],
                "recommended_action": "targeted_repair",
            },
            "expected_valid": True,
        },
        "invalid_low_confidence": {
            "payload": {
                "incident_type": "NETWORK_ERROR",
                "confidence": 0.30,
                "hypothesis": "maybe proxy drift",
                "evidence_refs": [],
                "limitations": [],
                "recommended_action": "targeted_repair",
            },
            "expected_valid": True,  # still valid structurally; fails closed via human_review_required
        },
        "unknown_incident_type": {
            "payload": {
                "incident_type": "BOGUS_ERROR",
                "confidence": 0.82,
                "hypothesis": "unknown",
                "evidence_refs": [],
                "limitations": [],
                "recommended_action": "targeted_repair",
            },
            "expected_valid": False,
        },
        "invented_evidence_ref": {
            "payload": {
                "incident_type": "NETWORK_ERROR",
                "confidence": 0.82,
                "hypothesis": "proxy drift",
                "evidence_refs": ["not-a-repair-ref"],
                "limitations": ["single window"],
                "recommended_action": "targeted_repair",
            },
            "expected_valid": True,
        },
        "missing_limitations_weak_evidence": {
            "payload": {
                "incident_type": "NETWORK_ERROR",
                "confidence": 0.30,
                "hypothesis": "proxy drift",
                "evidence_refs": ["repair:probe:WININET-001"],
                "limitations": [],
                "recommended_action": "targeted_repair",
            },
            "expected_valid": True,
        },
    }

    print("Model structured-output validation:")
    for name, case in cases.items():
        try:
            diag = validate_and_build_diagnosis(
                case["payload"],
                model="structured-proposal-v1",
            )
            valid = True
        except Exception as exc:
            diag = None
            valid = False
        print(f"  {name}: valid={valid} expected={case['expected_valid']} -> {'OK' if valid == case['expected_valid'] else 'MISMATCH'}")
        if diag is not None:
            print(f"    diagnosis.confidence={diag.confidence:.2f} human_review_required={diag.human_review_required}")

    print()
    print("Repair proposal validation:")
    proposal_cases = [
        {
            "name": "valid_proposal",
            "kwargs": dict(
                incident_id="INC-001",
                incident_type="NETWORK_ERROR",
                hypothesis="proxy drift",
                evidence_refs=["repair:probe:WININET-001"],
                candidate_action="reset_proxy_configuration",
                risk_class="medium",
                rollback_strategy="restore_previous_proxy_config",
                verification_plan=["repair:targeted_check", "repair:regression_check"],
                limitations=["single window"],
            ),
            "expected_valid": True,
        },
        {
            "name": "forbidden_action",
            "kwargs": dict(
                incident_id="INC-001",
                incident_type="NETWORK_ERROR",
                hypothesis="reset firewall",
                evidence_refs=["repair:probe:WININET-001"],
                candidate_action="reset_firewall",
                risk_class="high",
                rollback_strategy="restore_firewall",
                verification_plan=["repair:targeted_check"],
                limitations=["single window"],
            ),
            "expected_valid": False,
        },
        {
            "name": "missing_rollback",
            "kwargs": dict(
                incident_id="INC-001",
                incident_type="NETWORK_ERROR",
                hypothesis="proxy drift",
                evidence_refs=["repair:probe:WININET-001"],
                candidate_action="targeted_repair",
                risk_class="low",
                rollback_strategy="",
                verification_plan=["repair:targeted_check"],
                limitations=["single window"],
            ),
            "expected_valid": False,
        },
        {
            "name": "missing_verification",
            "kwargs": dict(
                incident_id="INC-001",
                incident_type="NETWORK_ERROR",
                hypothesis="proxy drift",
                evidence_refs=["repair:probe:WININET-001"],
                candidate_action="targeted_repair",
                risk_class="low",
                rollback_strategy="revert_patch",
                verification_plan=[],
                limitations=["single window"],
            ),
            "expected_valid": False,
        },
    ]

    for case in proposal_cases:
        try:
            prop = build_proposal(**case["kwargs"])
            valid = True
        except ProposalValidationError as exc:
            prop = None
            valid = False
        expected = case["expected_valid"]
        print(f"  {case['name']}: valid={valid} expected={expected} -> {'OK' if valid == expected else 'MISMATCH'}")

    print()
    print("Policy gate on low-confidence escalation:")
    engine = PolicyEngine()
    for conf, retryable in [(0.30, True), (0.80, True), (0.80, False)]:
        decision = engine.decide(PolicyContext(failure_class="NETWORK_ERROR", confidence=conf, retryable=retryable, retry_count=0, retry_budget=2))
        print(f"  confidence={conf:.2f} retryable={retryable} -> {decision.action.value} {decision.reason}")

    print()
    print("Independent repair-plan evaluator:")
    evaluator = RepairPlanEvaluator()
    for case in proposal_cases:
        prop = None
        try:
            prop = build_proposal(**case["kwargs"])
        except ProposalValidationError:
            prop = None
        eval_result = evaluator.evaluate(prop)
        print(f"  {case['name']}:")
        print(f"    proposal_valid={eval_result.proposal_valid}")
        print(f"    policy_safe={eval_result.policy_safe}")
        print(f"    rollback_present={eval_result.rollback_present}")
        print(f"    verification_present={eval_result.verification_present}")
        print(f"    forbidden_action_detected={eval_result.forbidden_action_detected}")
        print(f"    unsupported_action_detected={eval_result.unsupported_action_detected}")
        print(f"    evidence_refs_valid={eval_result.evidence_refs_valid}")
        print(f"    pass={eval_result.pass_}")

    if args.audit:
        log = HashChainedAuditLog(args.audit)
        log.append("agent_eval", {"cases_run": list(cases.keys())})
        print()
        print(f"audit: appended to {args.audit}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ci-orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)
    classify = sub.add_parser("classify", help="Classify a CI error message")
    classify.add_argument("message")
    classify.set_defaults(func=cmd_classify)
    rank = sub.add_parser("rank", help="Rank failures by probable root cause")
    rank.add_argument("--pipeline", required=True)
    rank.add_argument("--failures", required=True)
    rank.add_argument("--audit")
    rank.set_defaults(func=cmd_rank)
    analyze = sub.add_parser("analyze", help="Analyze normalized GitHub Actions jobs and logs")
    analyze.add_argument("--jobs", required=True)
    analyze.add_argument("--logs")
    analyze.add_argument("--audit")
    analyze.set_defaults(func=cmd_analyze)
    demo = sub.add_parser("agent-demo", help="Run a bounded, non-destructive agent harness demo")
    demo.add_argument("--audit")
    demo.set_defaults(func=cmd_agent_demo)
    evals = sub.add_parser("agent-eval", help="Run harness validation + policy + independent evaluator checks")
    evals.add_argument("--audit")
    evals.set_defaults(func=cmd_agent_eval)
    return parser


def main():
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

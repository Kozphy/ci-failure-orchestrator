import json
import sys

from ci_failure_orchestrator.affected_tests import select_affected_tests
from ci_failure_orchestrator.command_agent import CommandCodingAgent
from ci_failure_orchestrator.evidence_signing import sign_evidence, verify_evidence
from ci_failure_orchestrator.models import Failure, RankedFailure, Stage
from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.policy import PolicyDecision
from ci_failure_orchestrator.production_evidence import build_production_evidence
from ci_failure_orchestrator.repair_planner import DeterministicRepairPlanner
from ci_failure_orchestrator.tournament import CandidateScore, TournamentResult
from ci_failure_orchestrator.agent_executor import ExecutionResult, PatchProposal
from ci_failure_orchestrator.agent_loop import EvaluationResult


def _plan():
    graph = PipelineGraph([Stage("typecheck")])
    failure = Failure(
        "typecheck",
        "TYPE_ERROR",
        confidence=0.95,
        metadata={"files": ["src/foo.py"]},
    )
    ranked = RankedFailure(failure, 0.95, 0, 0, 1, ["upstream"])
    return DeterministicRepairPlanner().plan(graph, ranked, {"typecheck"})


def test_command_agent_uses_stdin_json_contract():
    script = (
        "import json,sys; p=json.load(sys.stdin); "
        "json.dump({'summary':'fix','changed_files':['src/foo.py'],"
        "'patch':'diff --git a/src/foo.py b/src/foo.py','confidence':0.9},sys.stdout)"
    )
    agent = CommandCodingAgent("fake-cli", [sys.executable, "-c", script], timeout_seconds=5)
    proposal = agent.propose_patch(_plan())
    assert proposal.changed_files == ("src/foo.py",)
    assert proposal.confidence == 0.9
    assert agent.last_telemetry is not None
    assert agent.last_telemetry.returncode == 0


def test_affected_test_selection_is_conservative():
    selection = select_affected_tests(["src/pkg/foo.py"])
    assert selection.selected_tests == ("tests/pkg/test_foo.py",)
    assert not selection.fallback_to_full_suite

    fallback = select_affected_tests(["README.md"])
    assert fallback.fallback_to_full_suite


def test_signed_production_evidence_detects_tampering():
    proposal = PatchProposal("fake", "fix", ("src/foo.py",), "patch", 0.9)
    execution = ExecutionResult(True, "accepted", proposal)
    evaluation = EvaluationResult(True, True, 0.95, "passed")
    candidate = CandidateScore(
        "fake",
        execution,
        evaluation,
        0.01,
        100,
        0.2,
        0.8,
        True,
        "candidate admissible",
    )
    tournament = TournamentResult(candidate, (candidate,), "READY_FOR_POLICY_GATE", "winner")
    evidence = build_production_evidence(
        root_stage="typecheck",
        tournament=tournament,
        policy=PolicyDecision("READY_FOR_CANARY", "policy passed", False),
    )
    envelope = sign_evidence(evidence, secret=b"test-secret", key_id="test")
    assert verify_evidence(envelope, secret=b"test-secret")

    tampered_payload = dict(envelope.payload)
    tampered_payload["action"] = "BLOCK"
    tampered = type(envelope)(envelope.algorithm, envelope.key_id, tampered_payload, envelope.signature)
    assert not verify_evidence(tampered, secret=b"test-secret")

from ci_failure_orchestrator.event_bus import ControlPlaneEvent, EventType
from ci_failure_orchestrator.event_control_plane import (
    AgentName,
    CandidateStore,
    EventDrivenControlPlane,
    RepairCandidate,
    RiskEngine,
    VerificationResult,
)


class AllowPolicy:
    def allow(self, event):
        return True, ()


class BlockPolicy:
    def allow(self, event):
        return False, ("policy_block",)


class Worker:
    def __init__(self, name, patch_ref):
        self.name = name
        self.patch_ref = patch_ref

    def propose(self, event):
        return RepairCandidate(agent=self.name, summary="repair", patch_ref=self.patch_ref)


class Verifier:
    def verify(self, candidate):
        if candidate.agent is AgentName.OPENCLAW:
            return VerificationResult(True, 0.95, 0.95, 0.95)
        if candidate.agent is AgentName.CODEX:
            return VerificationResult(True, 0.99, 0.99, 0.99)
        return VerificationResult(False, 0.1, 0.1, 0.1, ("regression",))


class Publisher:
    def __init__(self):
        self.calls = []

    def create_draft_pr(self, event, candidate, risk):
        self.calls.append((event, candidate, risk))
        return "PR#123(draft)"


def make_event():
    return ControlPlaneEvent(EventType.CI, "github-actions", {"run_id": 42})


def test_policy_blocks_before_agents_run():
    publisher = Publisher()
    control = EventDrivenControlPlane(
        policy=BlockPolicy(),
        workers=[Worker(AgentName.OPENCLAW, "patch-1")],
        verifier=Verifier(),
        candidate_store=CandidateStore(),
        risk_engine=RiskEngine(),
        publisher=publisher,
    )

    result = control.handle(make_event())

    assert result.status == "blocked"
    assert result.candidates_seen == 0
    assert publisher.calls == []


def test_best_verified_candidate_creates_draft_pr():
    publisher = Publisher()
    control = EventDrivenControlPlane(
        policy=AllowPolicy(),
        workers=[
            Worker(AgentName.OPENCLAW, "patch-openclaw"),
            Worker(AgentName.CODEX, "patch-codex"),
            Worker(AgentName.AIDER, "patch-aider"),
        ],
        verifier=Verifier(),
        candidate_store=CandidateStore(),
        risk_engine=RiskEngine(),
        publisher=publisher,
    )

    result = control.handle(make_event())

    assert result.candidates_seen == 3
    assert result.selected_agent is AgentName.CODEX
    assert result.draft_pr_ref == "PR#123(draft)"
    assert result.status == "draft_pr_created"
    assert len(publisher.calls) == 1

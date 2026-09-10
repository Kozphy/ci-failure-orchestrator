from ci_failure_orchestrator.agent_router import (
    CandidateResult,
    WorkerProfile,
    route_workers,
    select_candidate,
)
from ci_failure_orchestrator.github_repair_adapter import AgentTask
from ci_failure_orchestrator.supervisor import RepairAuthority


def _task() -> AgentTask:
    return AgentTask(
        objective="fix",
        failure_class="lint",
        authority=RepairAuthority.AUTONOMOUS_PATCH,
        allowed_paths=("src/a.py",),
        required_gates=("targeted_tests",),
        forbidden_actions=("disable_required_checks",),
        evidence=("job=test",),
    )


def test_router_filters_by_authority_class_and_budget() -> None:
    workers = (
        WorkerProfile(
            "cheap",
            "provider-a",
            (RepairAuthority.AUTONOMOUS_PATCH,),
            ("lint",),
            max_cost_usd=0.2,
        ),
        WorkerProfile(
            "wrong-class",
            "provider-b",
            (RepairAuthority.AUTONOMOUS_PATCH,),
            ("typing",),
            max_cost_usd=0.1,
        ),
        WorkerProfile(
            "too-expensive",
            "provider-c",
            (RepairAuthority.AUTONOMOUS_PATCH,),
            ("lint",),
            max_cost_usd=3.0,
        ),
    )
    routed = route_workers(_task(), workers, remaining_cost_usd=1.0)
    assert [worker.name for worker in routed] == ["cheap"]


def test_unsafe_candidate_can_never_win() -> None:
    unsafe = CandidateResult(
        "cheap", "a", "p1", True, False, True, True, 0.01, 100, 2, 0.99
    )
    safe = CandidateResult(
        "safe", "b", "p2", True, True, True, True, 0.5, 500, 20, 0.8
    )
    decision = select_candidate((unsafe, safe))
    assert decision.winner == safe
    assert unsafe in decision.rejected


def test_tournament_prefers_lowest_cost_safe_candidate() -> None:
    fast_expensive = CandidateResult(
        "fast", "a", "p1", True, True, True, True, 1.0, 100, 10, 0.9
    )
    cheap_slow = CandidateResult(
        "cheap", "b", "p2", True, True, True, True, 0.2, 1000, 30, 0.8
    )
    decision = select_candidate((fast_expensive, cheap_slow))
    assert decision.winner == cheap_slow


def test_tournament_escalates_when_no_safe_candidate() -> None:
    candidate = CandidateResult(
        "bad", "a", "p1", False, True, True, True, 0.1, 100, 3, 0.9
    )
    decision = select_candidate((candidate,))
    assert decision.winner is None
    assert decision.reason == "no_safe_candidate"

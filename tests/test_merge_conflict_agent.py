from ci_failure_orchestrator.agent_executor import CodingAgentExecutor
from ci_failure_orchestrator.merge_conflict_agent import MergeConflictRepairAgent
from ci_failure_orchestrator.repair_planner import RepairPlan


def _plan(*paths: str) -> RepairPlan:
    return RepairPlan(
        root_stage="merge",
        hypothesis="git merge conflict blocks the pull request",
        target_files=paths,
        proposed_change="resolve only planner-approved conflict blocks",
        verification=(),
        risk="medium",
        requires_human_approval=False,
    )


def test_resolves_one_sided_addition_and_emits_diff():
    files = {
        "config.txt": "before\n<<<<<<< HEAD\n=======\nnew_setting=true\n>>>>>>> feature\nafter\n"
    }
    agent = MergeConflictRepairAgent(file_loader=files.__getitem__)

    proposal = agent.propose_patch(_plan("config.txt"))

    assert proposal.changed_files == ("config.txt",)
    assert "new_setting=true" in proposal.patch
    assert "<<<<<<<" in proposal.patch  # removed lines remain visible in the unified diff
    assert proposal.metadata["decision"] == "propose_for_evaluation"


def test_refuses_semantic_conflict_and_fails_closed():
    files = {
        "policy.py": "<<<<<<< HEAD\nreturn Decision.BLOCK\n=======\nreturn Decision.RELEASE\n>>>>>>> feature\n"
    }
    agent = MergeConflictRepairAgent(file_loader=files.__getitem__)

    proposal = agent.propose_patch(_plan("policy.py"))

    assert proposal.patch == ""
    assert proposal.changed_files == ()
    assert proposal.metadata["decision"] == "escalate"
    result = CodingAgentExecutor().execute(agent, _plan("policy.py"))
    assert result.accepted is False
    assert result.reason == "agent returned an empty patch"


def test_executor_preserves_planner_file_scope():
    files = {
        "README.md": "<<<<<<< HEAD\ntext\n=======\ntext\nextra\n>>>>>>> feature\n",
    }
    agent = MergeConflictRepairAgent(file_loader=files.__getitem__)
    result = CodingAgentExecutor().execute(agent, _plan("README.md"))

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.changed_files == ("README.md",)

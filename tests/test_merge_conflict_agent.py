from ci_failure_orchestrator.agent_executor import CodingAgentExecutor
from ci_failure_orchestrator.merge_conflict_agent import (
    ChainedMergeResolver,
    ConservativeMergeResolver,
    MergeConflictRepairAgent,
    SemanticMergeResolver,
    SemanticResolution,
)
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


class _FakeSemanticProvider:
    def __init__(self, result: SemanticResolution):
        self.result = result
        self.calls = 0

    def resolve_conflict(self, **kwargs) -> SemanticResolution:
        self.calls += 1
        return self.result


def test_resolves_one_sided_addition_and_emits_diff():
    files = {
        "config.txt": "before\n<<<<<<< HEAD\n=======\nnew_setting=true\n>>>>>>> feature\nafter\n"
    }
    agent = MergeConflictRepairAgent(file_loader=files.__getitem__)

    proposal = agent.propose_patch(_plan("config.txt"))

    assert proposal.changed_files == ("config.txt",)
    assert "new_setting=true" in proposal.patch
    assert "<<<<<<<" in proposal.patch
    assert proposal.metadata["decision"] == "propose_for_evaluation"


def test_refuses_semantic_conflict_and_fails_closed_without_fallback():
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


def test_semantic_fallback_resolves_ambiguous_block_for_evaluation():
    files = {
        "policy.py": "<<<<<<< HEAD\nreturn Decision.BLOCK\n=======\nreturn Decision.RELEASE\n>>>>>>> feature\n"
    }
    provider = _FakeSemanticProvider(
        SemanticResolution(
            resolved_text="return policy_decide(context)\n",
            confidence=0.93,
            rationale="preserve centralized policy authority",
        )
    )
    resolver = ChainedMergeResolver(
        ConservativeMergeResolver(),
        SemanticMergeResolver(provider, min_confidence=0.80),
    )
    agent = MergeConflictRepairAgent(file_loader=files.__getitem__, resolver=resolver)

    proposal = agent.propose_patch(_plan("policy.py"))

    assert proposal.changed_files == ("policy.py",)
    assert "return policy_decide(context)" in proposal.patch
    assert provider.calls == 1
    assert proposal.metadata["decision"] == "propose_for_evaluation"


def test_low_confidence_semantic_resolution_escalates():
    files = {
        "policy.py": "<<<<<<< HEAD\nblock()\n=======\nrelease()\n>>>>>>> feature\n"
    }
    provider = _FakeSemanticProvider(
        SemanticResolution("release()\n", confidence=0.51, rationale="uncertain")
    )
    resolver = ChainedMergeResolver(
        ConservativeMergeResolver(),
        SemanticMergeResolver(provider, min_confidence=0.80),
    )
    proposal = MergeConflictRepairAgent(
        file_loader=files.__getitem__, resolver=resolver
    ).propose_patch(_plan("policy.py"))

    assert proposal.patch == ""
    assert proposal.metadata["decision"] == "escalate"


def test_semantic_resolution_with_conflict_markers_is_rejected():
    files = {
        "policy.py": "<<<<<<< HEAD\nblock()\n=======\nrelease()\n>>>>>>> feature\n"
    }
    provider = _FakeSemanticProvider(
        SemanticResolution(
            "<<<<<<< model\nblock()\n=======\nrelease()\n>>>>>>> model\n",
            confidence=0.99,
        )
    )
    resolver = SemanticMergeResolver(provider)
    proposal = MergeConflictRepairAgent(
        file_loader=files.__getitem__, resolver=resolver
    ).propose_patch(_plan("policy.py"))

    assert proposal.patch == ""
    assert proposal.metadata["decision"] == "escalate"


def test_executor_preserves_planner_file_scope():
    files = {
        "README.md": "<<<<<<< HEAD\ntext\n=======\ntext\nextra\n>>>>>>> feature\n",
    }
    agent = MergeConflictRepairAgent(file_loader=files.__getitem__)
    result = CodingAgentExecutor().execute(agent, _plan("README.md"))

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.changed_files == ("README.md",)

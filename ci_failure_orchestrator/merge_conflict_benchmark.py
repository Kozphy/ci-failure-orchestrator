from __future__ import annotations

from dataclasses import asdict, dataclass

from .merge_conflict_agent import ChainedMergeResolver, ConservativeMergeResolver, MergeConflictRepairAgent, MergeConflictResolver
from .repair_planner import RepairPlan


@dataclass(frozen=True)
class MergeConflictCaseResult:
    case_id: str
    category: str
    resolved: bool
    exact_match: bool
    escalated: bool
    unsafe_output: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MergeConflictMetrics:
    cases: int
    auto_resolution_rate: float
    exact_match_rate: float
    escalation_rate: float
    semantic_escalation_precision: float
    unsafe_output_rate: float

    def to_dict(self) -> dict:
        return asdict(self)


def _plan(path: str) -> RepairPlan:
    return RepairPlan(
        root_stage="merge",
        hypothesis="git merge conflict blocks the pull request",
        target_files=(path,),
        proposed_change="resolve only planner-approved conflict blocks",
        verification=(),
        risk="medium",
        requires_human_approval=False,
    )


def _added_lines(patch: str) -> list[str]:
    return [
        line[1:]
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def evaluate_merge_conflict_case(
    case: dict,
    *,
    semantic_resolver: MergeConflictResolver | None = None,
) -> MergeConflictCaseResult:
    resolver: MergeConflictResolver
    if semantic_resolver is None:
        resolver = ConservativeMergeResolver()
    else:
        resolver = ChainedMergeResolver(ConservativeMergeResolver(), semantic_resolver)

    files = {case["path"]: case["content"]}
    agent = MergeConflictRepairAgent(file_loader=files.__getitem__, resolver=resolver)
    proposal = agent.propose_patch(_plan(case["path"]))
    escalated = proposal.metadata.get("decision") == "escalate"
    resolved = bool(proposal.patch)
    added = _added_lines(proposal.patch)
    unsafe_output = resolved and any(
        marker in line for line in added for marker in ("<<<<<<<", "=======", ">>>>>>>")
    )

    expected = case.get("expected")
    exact_match = False
    if expected is not None and resolved:
        expected_lines = [line for line in expected.splitlines() if line]
        patch_lines = proposal.patch.splitlines()
        exact_match = all(any(line in patch_line for patch_line in patch_lines) for line in expected_lines)

    return MergeConflictCaseResult(
        case_id=case["id"],
        category=case.get("category", "unknown"),
        resolved=resolved,
        exact_match=exact_match,
        escalated=escalated,
        unsafe_output=unsafe_output,
    )


def summarize_merge_conflict_results(results: list[MergeConflictCaseResult]) -> MergeConflictMetrics:
    if not results:
        return MergeConflictMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0)

    semantic = [r for r in results if r.category == "semantic"]
    semantic_escalations = sum(r.escalated for r in semantic)
    return MergeConflictMetrics(
        cases=len(results),
        auto_resolution_rate=round(sum(r.resolved for r in results) / len(results), 4),
        exact_match_rate=round(sum(r.exact_match for r in results) / len(results), 4),
        escalation_rate=round(sum(r.escalated for r in results) / len(results), 4),
        semantic_escalation_precision=round(semantic_escalations / len(semantic), 4) if semantic else 0.0,
        unsafe_output_rate=round(sum(r.unsafe_output for r in results) / len(results), 4),
    )

from __future__ import annotations

from dataclasses import dataclass
import difflib
from pathlib import Path
import re
from typing import Callable, Protocol

from .agent_executor import PatchProposal
from .repair_planner import RepairPlan


_CONFLICT_RE = re.compile(
    r"<<<<<<<[^\n]*\n(?P<ours>.*?)^=======\n(?P<theirs>.*?)^>>>>>>>[^\n]*(?:\n|$)",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class ConflictBlock:
    ours: str
    theirs: str


class MergeConflictResolver(Protocol):
    def resolve(self, *, path: str, block: ConflictBlock, plan: RepairPlan) -> str | None:
        """Return resolved text for one block, or None to escalate ambiguity."""
        ...


class ConservativeMergeResolver:
    """Deterministic resolver for only unambiguous merge-conflict cases.

    It intentionally refuses semantic conflicts. Those can be delegated to a model
    backed resolver later, but the same sandbox/evaluator/policy boundaries remain.
    """

    def resolve(self, *, path: str, block: ConflictBlock, plan: RepairPlan) -> str | None:
        ours = block.ours
        theirs = block.theirs
        if ours == theirs:
            return ours
        if not ours.strip():
            return theirs
        if not theirs.strip():
            return ours
        # If one side strictly contains the other, preserve the superset. This is
        # useful for additive documentation/config changes and remains deterministic.
        if ours in theirs:
            return theirs
        if theirs in ours:
            return ours
        return None


class MergeConflictRepairAgent:
    """Proposal-only coding agent for bounded Git merge-conflict resolution.

    The agent never writes to the repository. It reads only planner-approved files,
    resolves conflict blocks through an injected resolver, and emits a unified diff.
    Any ambiguous block produces an empty proposal so CodingAgentExecutor fails
    closed and the orchestrator can escalate to a stronger agent or a human.
    """

    name = "merge-conflict-repair"

    def __init__(
        self,
        file_loader: Callable[[str], str] | None = None,
        resolver: MergeConflictResolver | None = None,
    ) -> None:
        self.file_loader = file_loader or (lambda path: Path(path).read_text(encoding="utf-8"))
        self.resolver = resolver or ConservativeMergeResolver()

    def propose_patch(self, plan: RepairPlan) -> PatchProposal:
        changed_files: list[str] = []
        patches: list[str] = []
        conflict_blocks = 0

        for path in plan.target_files:
            original = self.file_loader(path)
            matches = list(_CONFLICT_RE.finditer(original))
            if not matches:
                continue

            conflict_blocks += len(matches)
            resolved_parts: list[str] = []
            cursor = 0
            for match in matches:
                resolved_parts.append(original[cursor : match.start()])
                block = ConflictBlock(match.group("ours"), match.group("theirs"))
                resolution = self.resolver.resolve(path=path, block=block, plan=plan)
                if resolution is None:
                    return PatchProposal(
                        provider=self.name,
                        summary=f"ambiguous merge conflict in {path}; escalation required",
                        changed_files=(),
                        patch="",
                        confidence=0.0,
                        metadata={
                            "conflict_blocks": str(conflict_blocks),
                            "decision": "escalate",
                            "ambiguous_path": path,
                        },
                    )
                resolved_parts.append(resolution)
                cursor = match.end()
            resolved_parts.append(original[cursor:])
            resolved = "".join(resolved_parts)

            if "<<<<<<<" in resolved or "=======" in resolved or ">>>>>>>" in resolved:
                return PatchProposal(
                    provider=self.name,
                    summary=f"unparsed conflict markers remain in {path}; escalation required",
                    changed_files=(),
                    patch="",
                    confidence=0.0,
                    metadata={"decision": "escalate", "ambiguous_path": path},
                )

            diff = "".join(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    resolved.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
            if diff:
                changed_files.append(path)
                patches.append(diff)

        if not changed_files:
            return PatchProposal(
                provider=self.name,
                summary="no planner-approved merge conflicts found",
                changed_files=(),
                patch="",
                confidence=0.0,
                metadata={"decision": "no_op", "conflict_blocks": str(conflict_blocks)},
            )

        return PatchProposal(
            provider=self.name,
            summary=f"resolved {conflict_blocks} unambiguous merge-conflict block(s)",
            changed_files=tuple(changed_files),
            patch="\n".join(patches),
            confidence=0.90,
            metadata={
                "conflict_blocks": str(conflict_blocks),
                "decision": "propose_for_evaluation",
                "resolver": self.resolver.__class__.__name__,
            },
        )

"""Merge conflict resolution agent with bounded autonomy.

This module provides a proposal-only coding agent for Git merge-conflict resolution.
The agent reads only planner-approved files, resolves conflict blocks through
injected resolvers, and emits unified diffs. It never writes to the repository,
ensuring that all changes go through independent evaluation and approval.
"""

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
    """Represents a single Git merge-conflict block.

    Attributes:
        ours: The local/our side of the conflict.
        theirs: The incoming/their side of the conflict.
    """

    ours: str
    theirs: str


@dataclass(frozen=True)
class SemanticResolution:
    """Result from a semantic merge-conflict resolution provider.

    Attributes:
        resolved_text: The proposed resolved text for the conflict block.
        confidence: Confidence score (0.0 to 1.0) in the resolution quality.
        rationale: Human-readable explanation of the resolution decision.
    """

    resolved_text: str
    confidence: float
    rationale: str = ""


class MergeConflictResolver(Protocol):
    """Protocol for merge-conflict resolution strategies."""

    def resolve(self, *, path: str, block: ConflictBlock, plan: RepairPlan) -> str | None:
        """Resolve a single merge-conflict block.

        Args:
            path: File path containing the conflict.
            block: The conflict block with ours and theirs sides.
            plan: Repair plan providing context and hypothesis.

        Returns:
            Resolved text for the block, or None to escalate ambiguity.
        """
        ...


class SemanticResolutionProvider(Protocol):
    """Protocol for semantic merge-conflict resolution providers (e.g., LLMs)."""

    def resolve_conflict(
        self,
        *,
        path: str,
        ours: str,
        theirs: str,
        hypothesis: str,
        proposed_change: str,
    ) -> SemanticResolution:
        """Resolve a conflict block using semantic understanding.

        Args:
            path: File path containing the conflict.
            ours: Local side of the conflict.
            theirs: Incoming side of the conflict.
            hypothesis: Repair hypothesis from the planner.
            proposed_change: Proposed change context.

        Returns:
            SemanticResolution with resolved text, confidence, and rationale.
        """
        ...


class ConservativeMergeResolver:
    """Deterministic resolver for only unambiguous merge-conflict cases.

    This resolver handles only deterministic, unambiguous cases such as identical
    sides, one-sided additions, or strict superset edits. Any ambiguous case is
    escalated rather than guessed.

    Resolution Logic:
        - Identical sides: Return either side.
        - Empty ours: Return theirs.
        - Empty theirs: Return ours.
        - Ours in theirs: Return theirs (superset).
        - Theirs in ours: Return ours (superset).
        - Otherwise: Escalate (return None).
    """

    def resolve(self, *, path: str, block: ConflictBlock, plan: RepairPlan) -> str | None:
        """Resolve a conflict block using deterministic rules.

        Args:
            path: File path containing the conflict (unused in deterministic logic).
            block: The conflict block with ours and theirs sides.
            plan: Repair plan (unused in deterministic logic).

        Returns:
            Resolved text for unambiguous cases, or None to escalate ambiguity.
        """
        ours = block.ours
        theirs = block.theirs
        if ours == theirs:
            return ours
        if not ours.strip():
            return theirs
        if not theirs.strip():
            return ours
        if ours in theirs:
            return theirs
        if theirs in ours:
            return ours
        return None


class SemanticMergeResolver:
    """Bounded semantic fallback for ambiguous conflict blocks.

    This resolver can use an LLM or other semantic provider, but enforces strict
    safety constraints before model output can become a patch candidate. The
    semantic path fails closed when confidence is below threshold, output is
    empty or oversized, or conflict markers remain.

    Attributes:
        provider: Semantic resolution provider (e.g., LLM-based).
        min_confidence: Minimum confidence threshold for accepting resolutions.
        max_resolved_chars: Maximum character limit for resolved text.

    Safety Constraints:
        - Confidence must meet or exceed min_confidence.
        - Resolved text must be non-empty.
        - Resolved text must not exceed max_resolved_chars.
        - Resolved text must not contain conflict markers.

    Audit Notes:
        - LLM output can introduce subtle logic errors or security vulnerabilities.
        - Confidence thresholds may be misconfigured or bypassed.
        - Recovery: Review all semantic resolutions in human-in-the-loop mode before promotion.
        - Evidence: All semantic resolutions include confidence scores and rationale for audit.
    """

    def __init__(
        self,
        provider: SemanticResolutionProvider,
        *,
        min_confidence: float = 0.80,
        max_resolved_chars: int = 20_000,
    ) -> None:
        """Initialize the semantic merge resolver.

        Args:
            provider: Semantic resolution provider (e.g., LLM-based).
            min_confidence: Minimum confidence threshold (default: 0.80).
            max_resolved_chars: Maximum character limit for resolved text (default: 20,000).
        """
        self.provider = provider
        self.min_confidence = min_confidence
        self.max_resolved_chars = max_resolved_chars

    def resolve(self, *, path: str, block: ConflictBlock, plan: RepairPlan) -> str | None:
        """Resolve a conflict block using semantic understanding with safety constraints.

        Args:
            path: File path containing the conflict.
            block: The conflict block with ours and theirs sides.
            plan: Repair plan providing context and hypothesis.

        Returns:
            Resolved text if all safety constraints are met, or None to escalate.

        Safety Checks:
            - Confidence >= min_confidence
            - Resolved text is non-empty
            - Resolved text length <= max_resolved_chars
            - No conflict markers remain in resolved text
        """
        result = self.provider.resolve_conflict(
            path=path,
            ours=block.ours,
            theirs=block.theirs,
            hypothesis=plan.hypothesis,
            proposed_change=plan.proposed_change,
        )
        text = result.resolved_text
        if result.confidence < self.min_confidence:
            return None
        if not text.strip():
            return None
        if len(text) > self.max_resolved_chars:
            return None
        if any(marker in text for marker in ("<<<<<<<", "=======", ">>>>>>>")):
            return None
        return text


class ChainedMergeResolver:
    """Prefer deterministic resolution; use semantic resolution only as fallback.

    This resolver chains multiple resolvers in order, preferring deterministic
    resolution and using semantic resolution only as a fallback for ambiguous
    cases. This ensures that safe, deterministic methods are tried first.

    Attributes:
        resolvers: Ordered tuple of resolvers to try in sequence.
    """

    def __init__(self, *resolvers: MergeConflictResolver) -> None:
        """Initialize the chained merge resolver.

        Args:
            *resolvers: Ordered resolvers to try in sequence (first successful wins).
        """
        self.resolvers = resolvers

    def resolve(self, *, path: str, block: ConflictBlock, plan: RepairPlan) -> str | None:
        """Resolve a conflict block by trying resolvers in sequence.

        Args:
            path: File path containing the conflict.
            block: The conflict block with ours and theirs sides.
            plan: Repair plan providing context and hypothesis.

        Returns:
            Resolved text from the first successful resolver, or None if all fail.
        """
        for resolver in self.resolvers:
            resolution = resolver.resolve(path=path, block=block, plan=plan)
            if resolution is not None:
                return resolution
        return None


class MergeConflictRepairAgent:
    """Proposal-only coding agent for bounded Git merge-conflict resolution.

    The agent never writes to the repository. It reads only planner-approved files,
    resolves conflict blocks through an injected resolver, and emits a unified diff.
    Any unresolved block produces an empty proposal so CodingAgentExecutor fails
    closed and the orchestrator can escalate to another agent or a human.

    This separation ensures that model output cannot directly invoke filesystem,
    shell, git, merge, or release operations. All changes require independent
    verification through the evaluation pipeline.

    Attributes:
        name: Agent identifier for logging and audit.
        file_loader: Function to read file contents (default: Path.read_text).
        resolver: Merge conflict resolver to use (default: ConservativeMergeResolver).

    Audit Notes:
        - Unresolved conflicts produce empty proposals that trigger escalation.
        - The agent has no write access to the repository.
        - All changes go through independent evaluation and approval.
        - Recovery: Review escalation logs and unresolved conflict blocks.
        - Evidence: All proposals include resolver type, conflict count, and decision rationale.
    """

    name = "merge-conflict-repair"

    def __init__(
        self,
        file_loader: Callable[[str], str] | None = None,
        resolver: MergeConflictResolver | None = None,
    ) -> None:
        """Initialize the merge conflict repair agent.

        Args:
            file_loader: Optional function to read file contents. Defaults to Path.read_text.
            resolver: Optional merge conflict resolver. Defaults to ConservativeMergeResolver.
        """
        self.file_loader = file_loader or (lambda path: Path(path).read_text(encoding="utf-8"))
        self.resolver = resolver or ConservativeMergeResolver()

    def propose_patch(self, plan: RepairPlan) -> PatchProposal:
        """Generate a patch proposal for merge-conflict resolution.

        This method reads only planner-approved files, detects conflict blocks,
        resolves them using the configured resolver, and generates a unified diff.
        Any unresolved or ambiguous conflict block triggers escalation.

        Args:
            plan: Repair plan specifying target files and repair context.

        Returns:
            PatchProposal with resolved conflicts as a unified diff, or an empty
            proposal with escalation metadata if any conflict cannot be resolved.

        Escalation Conditions:
            - Ambiguous conflict block that the resolver cannot handle.
            - Unparsed conflict markers remain after resolution.
            - No planner-approved merge conflicts found.

        Side Effects:
            - Reads file contents from planner-approved paths only.
            - Generates unified diffs for changed files.
            - Never writes to the filesystem.
        """
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
                            "resolver": self.resolver.__class__.__name__,
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
            summary=f"resolved {conflict_blocks} merge-conflict block(s) for evaluation",
            changed_files=tuple(changed_files),
            patch="\n".join(patches),
            confidence=0.90,
            metadata={
                "conflict_blocks": str(conflict_blocks),
                "decision": "propose_for_evaluation",
                "resolver": self.resolver.__class__.__name__,
            },
        )

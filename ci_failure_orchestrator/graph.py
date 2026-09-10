"""Pipeline dependency graph for CI failure analysis.

This module provides a directed acyclic graph (DAG) representation of CI pipeline
stages and their dependencies, supporting operations like depth calculation,
descendant traversal, and upstream relationship queries.
"""

from __future__ import annotations

from collections import defaultdict, deque

from .models import Stage


class PipelineGraph:
    """Directed acyclic graph representing CI pipeline stage dependencies.

    This class builds a dependency graph from pipeline stages and provides
    graph traversal operations for root-cause analysis and failure propagation
    tracking. The graph is validated to ensure it is acyclic.

    Attributes:
        stages: Dictionary mapping stage IDs to Stage objects.
        children: Dictionary mapping parent stage IDs to sets of child stage IDs.

    Raises:
        ValueError: If pipeline dependencies contain a cycle or reference unknown stages.

    Audit Notes:
        - Invalid graphs (cycles, unknown dependencies) prevent pipeline analysis.
        - Graph validation ensures DAG properties for correct traversal.
        - Recovery: Review pipeline configuration and fix dependency errors.
        - Evidence: Graph construction failures raise ValueError with descriptive messages.
    """

    def __init__(self, stages: list[Stage]):
        """Initialize the pipeline graph from a list of stages.

        Args:
            stages: List of Stage objects with dependency information.

        Raises:
            ValueError: If dependencies reference unknown stages or contain cycles.
        """
        self.stages = {s.id: s for s in stages}
        self.children: dict[str, set[str]] = defaultdict(set)
        for stage in stages:
            for parent in stage.depends_on:
                if parent not in self.stages:
                    raise ValueError(f"Unknown dependency {parent!r} for stage {stage.id!r}")
                self.children[parent].add(stage.id)
        self._validate_acyclic()

    def _validate_acyclic(self) -> None:
        """Validate that the pipeline graph is acyclic using Kahn's algorithm.

        Raises:
            ValueError: If the pipeline dependencies contain a cycle.
        """
        indegree = {sid: 0 for sid in self.stages}
        for stage in self.stages.values():
            for _ in stage.depends_on:
                indegree[stage.id] += 1
        queue = deque([sid for sid, degree in indegree.items() if degree == 0])
        seen = 0
        while queue:
            current = queue.popleft()
            seen += 1
            for child in self.children.get(current, ()):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if seen != len(self.stages):
            raise ValueError("Pipeline dependencies contain a cycle")

    def depth(self, stage_id: str) -> int:
        """Calculate the depth of a stage in the dependency graph.

        Depth is defined as the maximum number of edges from any root stage
        (stage with no dependencies) to the target stage.

        Args:
            stage_id: ID of the stage to calculate depth for.

        Returns:
            Depth of the stage (0 for root stages, >0 for dependent stages).

        Raises:
            KeyError: If stage_id is not in the graph.
        """
        memo: dict[str, int] = {}

        def visit(node: str) -> int:
            if node in memo:
                return memo[node]
            deps = self.stages[node].depends_on
            memo[node] = 0 if not deps else 1 + max(visit(parent) for parent in deps)
            return memo[node]

        return visit(stage_id)

    def descendants(self, stage_id: str) -> set[str]:
        """Find all descendant stages of a given stage.

        Descendants are stages that transitively depend on the given stage
        (direct children, grandchildren, etc.).

        Args:
            stage_id: ID of the stage to find descendants for.

        Returns:
            Set of descendant stage IDs (empty if stage has no descendants).
        """
        result: set[str] = set()
        stack = list(self.children.get(stage_id, ()))
        while stack:
            node = stack.pop()
            if node in result:
                continue
            result.add(node)
            stack.extend(self.children.get(node, ()))
        return result

    def is_upstream(self, possible_parent: str, possible_child: str) -> bool:
        """Check if one stage is upstream of another.

        An upstream stage is a parent, grandparent, or earlier ancestor in the
        dependency chain (i.e., the possible_child depends on possible_parent).

        Args:
            possible_parent: ID of the potential upstream stage.
            possible_child: ID of the potential downstream stage.

        Returns:
            True if possible_parent is upstream of possible_child, False otherwise.
        """
        return possible_child in self.descendants(possible_parent)

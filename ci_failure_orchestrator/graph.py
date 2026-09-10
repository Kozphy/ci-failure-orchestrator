from __future__ import annotations

"""Pipeline dependency graph for CI failure analysis.

This module provides graph-based utilities for representing and
querying CI/CD pipeline stage dependencies. It supports root
cause analysis by identifying upstream stages that potentially
caused downstream failures.

Module responsibility:
    - Build dependency graph from Stage definitions
    - Validate graph acyclicity
    - Compute stage depths (distance from root)
    - Find downstream descendants of a stage
    - Check upstream/downstream relationships

Key invariants:
    - Graph is validated to be acyclic on construction
    - Unknown dependencies raise ValueError
    - Depth is computed as max path length from root

Failure modes:
    - Unknown dependency: ValueError raised during construction
    - Cyclic dependencies: ValueError raised during construction

Audit Notes:
    - Graph validation happens at construction time (fail-fast)
    - All queries are pure functions from the graph state
    - Children map is pre-computed for efficient traversal
"""

from collections import defaultdict, deque

from .models import Stage


class PipelineGraph:
    """Directed acyclic graph of pipeline stage dependencies.

    Represents the CI/CD pipeline as a DAG where edges point from
    dependencies to dependents. Provides efficient queries for
    root cause analysis.

    Responsibility:
        - Store stage definitions and dependency relationships
        - Validate graph is acyclic
        - Answer depth and descendant queries

    Invariants:
        - stages dict maps stage ID to Stage object
        - children dict maps stage ID to set of direct child IDs
        - Graph is always acyclic (validated at construction)

    Usage:
        graph = PipelineGraph([Stage("build"), Stage("test", depends_on=("build",))])
        depth = graph.depth("test")  # returns 1
        descendants = graph.descendants("build")  # returns {"test"}

    Side effects:
        - Construction validates acyclicity (raises ValueError if cyclic)

    Audit Notes:
        - Acyclicity validation uses topological sort (Kahn's algorithm)
        - Depth computation uses memoization for efficiency
        - Unknown dependencies raise ValueError immediately
    """

    def __init__(self, stages: list[Stage]):
        """Initialize with list of Stage definitions.

        Args:
            stages: List of Stage objects defining the pipeline

        Raises:
            ValueError: If any stage has an unknown dependency
            ValueError: If the dependency graph contains a cycle

        Side effects:
            Builds stages dict and children adjacency map.
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
        """Validate that the dependency graph contains no cycles.

        Uses Kahn's algorithm (topological sort) to detect cycles.

        Raises:
            ValueError: If a cycle is detected

        Side effects:
            None.
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
        """Compute the depth of a stage in the dependency graph.

        Depth is the length of the longest path from a root (no dependencies)
        to this stage. Root stages have depth 0.

        Args:
            stage_id: ID of the stage to compute depth for

        Returns:
            Depth of the stage (0 for root stages)

        Side effects:
            None.
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
        """Find all downstream stages reachable from a given stage.

        Returns the transitive closure of direct and indirect children.

        Args:
            stage_id: ID of the stage to find descendants for

        Returns:
            Set of all downstream stage IDs

        Side effects:
            None.
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
        """Check if one stage is an ancestor of another.

        Args:
            possible_parent: Potential upstream stage ID
            possible_child: Potential downstream stage ID

        Returns:
            True if possible_parent is an ancestor of possible_child, False otherwise

        Side effects:
            None.
        """
        return possible_child in self.descendants(possible_parent)

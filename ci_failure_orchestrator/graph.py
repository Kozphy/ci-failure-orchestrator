from __future__ import annotations

from collections import defaultdict, deque

from .models import Stage


class PipelineGraph:
    def __init__(self, stages: list[Stage]):
        self.stages = {s.id: s for s in stages}
        self.children: dict[str, set[str]] = defaultdict(set)
        for stage in stages:
            for parent in stage.depends_on:
                if parent not in self.stages:
                    raise ValueError(f"Unknown dependency {parent!r} for stage {stage.id!r}")
                self.children[parent].add(stage.id)
        self._validate_acyclic()

    def _validate_acyclic(self) -> None:
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
        memo: dict[str, int] = {}

        def visit(node: str) -> int:
            if node in memo:
                return memo[node]
            deps = self.stages[node].depends_on
            memo[node] = 0 if not deps else 1 + max(visit(parent) for parent in deps)
            return memo[node]

        return visit(stage_id)

    def descendants(self, stage_id: str) -> set[str]:
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
        return possible_child in self.descendants(possible_parent)

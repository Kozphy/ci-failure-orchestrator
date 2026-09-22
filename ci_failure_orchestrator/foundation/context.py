"""Budgeted, prioritized, sanitized FailureContext builder."""

from __future__ import annotations

from dataclasses import dataclass

from .models import FailureContext, FailureEvent
from .sanitization import is_binary_noise, sanitize_text


@dataclass(frozen=True)
class ContextBudget:
    max_chars: int = 50_000
    max_log_chars: int = 12_000
    max_diff_chars: int = 15_000
    max_items: int = 40


class ContextBuildError(RuntimeError):
    pass


class ContextBuilder:
    """Assemble deterministic FailureContext for planning.

    Priority order:
    1. failing step
    2. error message / traceback
    3. related source paths
    4. related tests (from message)
    5. log excerpt
    6. repository metadata
    7. previous attempts
    """

    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()

    def build(
        self,
        event: FailureEvent,
        *,
        diff_excerpt: str = "",
        previous_attempts: tuple[dict, ...] = (),
    ) -> FailureContext:
        if not event.run_id:
            raise ContextBuildError("FailureEvent.run_id is required")

        items: list[str] = []
        reasons: list[str] = []
        redactions = 0
        truncated = False

        def add(label: str, value: str, limit: int | None = None) -> None:
            nonlocal redactions, truncated
            if is_binary_noise(value):
                reasons.append(f"skipped_binary:{label}")
                return
            cleaned, n = sanitize_text(value)
            redactions += n
            if limit is not None and len(cleaned) > limit:
                cleaned = cleaned[: max(0, limit - 24)] + "\n...[truncated]"
                truncated = True
                reasons.append(f"truncated:{label}")
            items.append(f"{label}: {cleaned}")

        # Priority 1–2
        add("failed_step", event.failed_step)
        add("message", event.message, limit=4_000)
        # Priority 3
        safe_paths = tuple(
            p.replace("\\", "/")
            for p in event.changed_paths
            if ".." not in p.replace("\\", "/") and not p.startswith(("/", "\\"))
        )
        if safe_paths:
            add("changed_paths", ", ".join(safe_paths))
        # Priority 4 — extract test hints from message/log
        for hay in (event.message, event.log_excerpt):
            if "test_" in hay or "::" in hay:
                add("test_hint", hay, limit=1_000)
                break
        # Priority 5
        if event.log_excerpt:
            add("log_excerpt", event.log_excerpt, limit=self.budget.max_log_chars)
        # Priority 6
        if event.repository:
            add("repository", event.repository)
        if event.commit_sha:
            add("commit_sha", event.commit_sha)
        if event.branch:
            add("branch", event.branch)
        if event.workflow:
            add("workflow", event.workflow)
        if event.job:
            add("job", event.job)
        # Diff
        if diff_excerpt:
            add("diff", diff_excerpt, limit=self.budget.max_diff_chars)
        # Priority 7 — deduped previous attempts
        seen: set[str] = set()
        for attempt in previous_attempts:
            key = str(attempt.get("summary") or attempt)
            if key in seen:
                continue
            seen.add(key)
            add("previous_attempt", key, limit=800)

        prioritized = tuple(items[: self.budget.max_items])
        blob = "\n".join(prioritized)
        if len(blob) > self.budget.max_chars:
            blob = blob[: self.budget.max_chars] + "\n...[context_budget]"
            truncated = True
            reasons.append("context_budget")
            prioritized = tuple(blob.splitlines())

        summary = (
            f"{event.workflow}/{event.job} failed at {event.failed_step}: "
            f"{sanitize_text(event.message)[0][:200]}"
        )
        return FailureContext(
            run_id=event.run_id,
            event_id=event.event_id,
            summary=summary,
            prioritized_evidence=prioritized,
            changed_paths=safe_paths,
            truncated=truncated,
            truncation_reasons=tuple(reasons),
            redactions_applied=redactions,
            char_count=len(blob),
        )

"""Context engineering: budgeted, redacted, prioritized failure evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..audit import redact
from .models import FailureContext, FailureEvent, new_id


_SECRETISH = re.compile(
    r"(?i)(api[_-]?key|password|secret|token|bearer\s+[a-z0-9._~+/=-]{8,})"
)


@dataclass(frozen=True)
class ContextBudget:
    """Maximum approximate characters/tokens for assembled context.

    ``max_tokens`` is a heuristic estimate (chars/4), not a provider tokenizer.
    """

    max_chars: int = 12_000
    max_log_chars: int = 4_000
    max_evidence_items: int = 24


class ContextBuilder:
    """Assemble deterministic, sanitized planning context."""

    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()

    def build(
        self,
        event: FailureEvent,
        *,
        previous_attempts: tuple[dict, ...] = (),
        extra_evidence: tuple[str, ...] = (),
    ) -> FailureContext:
        redactions = 0
        items: list[str] = []

        def add(label: str, value: str, limit: int | None = None) -> None:
            nonlocal redactions
            cleaned = str(redact(value))
            if _SECRETISH.search(cleaned):
                cleaned = _SECRETISH.sub("[REDACTED]", cleaned)
                redactions += 1
            if limit is not None and len(cleaned) > limit:
                cleaned = cleaned[: limit - 20] + "\n...[truncated]"
            items.append(f"{label}: {cleaned}")

        add("workflow", event.workflow)
        add("job", event.job)
        add("failed_step", event.failed_step)
        add("message", event.message, limit=2_000)
        if event.changed_paths:
            # Path sanitization: drop absolute / traversal-ish noise
            safe_paths = tuple(
                p.replace("\\", "/")
                for p in event.changed_paths
                if ".." not in p.replace("\\", "/") and not p.startswith("/")
            )
            add("changed_paths", ", ".join(safe_paths) or "(none)")
        if event.log_excerpt:
            add("log_excerpt", event.log_excerpt, limit=self.budget.max_log_chars)

        # Deduplicate previous attempt summaries
        seen: set[str] = set()
        for attempt in previous_attempts:
            key = str(attempt.get("summary") or attempt)
            if key in seen:
                continue
            seen.add(key)
            add("previous_attempt", key, limit=500)

        for item in extra_evidence:
            add("evidence", item, limit=800)

        # Prioritize: identity first, then message/paths, then logs/history
        prioritized = tuple(items[: self.budget.max_evidence_items])
        blob = "\n".join(prioritized)
        if len(blob) > self.budget.max_chars:
            blob = blob[: self.budget.max_chars] + "\n...[context_budget]"
            prioritized = tuple(blob.splitlines())

        summary = (
            f"{event.workflow}/{event.job} failed at {event.failed_step}: "
            f"{event.message[:200]}"
        )
        return FailureContext(
            run_id=event.run_id,
            event_id=event.event_id or new_id("evt"),
            summary=summary,
            prioritized_evidence=prioritized,
            changed_paths=event.changed_paths,
            previous_attempts=previous_attempts,
            token_estimate=max(1, len(blob) // 4),
            redactions_applied=redactions,
        )

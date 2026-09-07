from __future__ import annotations

import json
from time import perf_counter

from .merge_conflict_agent import SemanticResolution


class OpenAISemanticMergeProvider:
    """OpenAI-backed semantic merge provider with structured JSON output.

    The provider returns text only. It has no filesystem, git, shell, merge, or
    approval authority; all repository mutation and release decisions stay in the
    existing executor/evaluator/policy layers.
    """

    def __init__(self, *, model: str = "gpt-5.6", client=None) -> None:
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - optional integration
                raise RuntimeError(
                    "OpenAI integration requires the optional 'openai' dependency"
                ) from exc
            client = OpenAI()
        self.client = client
        self.model = model
        self.last_latency_seconds = 0.0
        self.last_input_tokens = 0
        self.last_output_tokens = 0

    def resolve_conflict(
        self,
        *,
        path: str,
        ours: str,
        theirs: str,
        hypothesis: str,
        proposed_change: str,
    ) -> SemanticResolution:
        schema = {
            "type": "object",
            "properties": {
                "resolved_text": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "rationale": {"type": "string"},
            },
            "required": ["resolved_text", "confidence", "rationale"],
            "additionalProperties": False,
        }
        prompt = (
            "Resolve exactly one Git merge-conflict block. Preserve compatible intent "
            "from both sides when possible. Do not emit conflict markers, markdown, "
            "shell commands, or explanations outside the JSON object. If the intended "
            "semantics are uncertain, return low confidence.\n\n"
            f"Path: {path}\n"
            f"Repair hypothesis: {hypothesis}\n"
            f"Planned change: {proposed_change}\n\n"
            f"OURS:\n{ours}\n\nTHEIRS:\n{theirs}"
        )

        started = perf_counter()
        response = self.client.responses.create(
            model=self.model,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "merge_conflict_resolution",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        self.last_latency_seconds = perf_counter() - started

        usage = getattr(response, "usage", None)
        if usage is not None:
            self.last_input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            self.last_output_tokens = int(getattr(usage, "output_tokens", 0) or 0)

        raw = getattr(response, "output_text", "")
        data = json.loads(raw)
        return SemanticResolution(
            resolved_text=data["resolved_text"],
            confidence=float(data["confidence"]),
            rationale=data["rationale"],
        )

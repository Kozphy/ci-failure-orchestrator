"""OpenAI integration for semantic merge-conflict resolution.

This module provides an OpenAI-backed semantic merge provider that uses LLM
reasoning to resolve ambiguous Git merge conflicts. The provider returns only
text with confidence scores and has no filesystem, git, shell, merge, or approval
authority. All repository mutation and release decisions remain in the existing
executor/evaluator/policy layers.
"""

from __future__ import annotations

import json
from time import perf_counter

from .merge_conflict_agent import SemanticResolution


class OpenAISemanticMergeProvider:
    """OpenAI-backed semantic merge provider with structured JSON output.

    This provider uses OpenAI's language models to perform semantic reasoning
    on Git merge conflicts, providing resolved text with confidence scores and
    rationales. It has no filesystem, git, shell, merge, or approval authority;
    all repository mutation and release decisions stay in the existing
    executor/evaluator/policy layers.

    Attributes:
        client: OpenAI client instance (defaults to OpenAI() if not provided).
        model: OpenAI model identifier (default: "gpt-5.6").
        last_latency_seconds: Latency of the last API call in seconds.
        last_input_tokens: Number of input tokens in the last API call.
        last_output_tokens: Number of output tokens in the last API call.

    Raises:
        RuntimeError: If OpenAI dependency is not installed.
        ImportError: If openai package cannot be imported.

    Audit Notes:
        - LLM output can introduce subtle logic errors or security vulnerabilities.
        - Provider has no filesystem, git, shell, merge, or approval authority.
        - All resolutions go through confidence thresholds in SemanticMergeResolver.
        - Recovery: Review resolution quality and adjust confidence thresholds if needed.
        - Evidence: All resolutions include confidence scores, rationales, and token usage for audit.

    Engineering Notes:
        - Trade-off: LLM semantic understanding is powerful but adds cost and latency.
        - Design: Structured JSON output ensures parseable responses with confidence scoring.
        - Performance: API latency and token costs are tracked for monitoring and cost control.
    """

    def __init__(self, *, model: str = "gpt-5.6", client=None) -> None:
        """Initialize the OpenAI semantic merge provider.

        Args:
            model: OpenAI model identifier (default: "gpt-5.6").
            client: Optional OpenAI client instance. Defaults to OpenAI() if not provided.

        Raises:
            RuntimeError: If OpenAI dependency is not installed.
        """
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
        """Resolve a merge conflict block using OpenAI semantic reasoning.

        This method sends the conflict block to the OpenAI API with a structured
        JSON schema, requesting resolved text, confidence score, and rationale.
        The provider has no authority to modify files or approve changes.

        Args:
            path: File path containing the conflict.
            ours: Local side of the conflict.
            theirs: Incoming side of the conflict.
            hypothesis: Repair hypothesis from the planner.
            proposed_change: Proposed change context.

        Returns:
            SemanticResolution with resolved text, confidence score, and rationale.

        Side Effects:
            - Makes external API call to OpenAI (network dependency).
            - Updates last_latency_seconds, last_input_tokens, last_output_tokens.

        API Configuration:
            - Uses structured JSON output with strict schema validation.
            - Model parameter defaults to "gpt-5.6" but can be overridden.
            - Response includes token usage for cost tracking.
        """
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

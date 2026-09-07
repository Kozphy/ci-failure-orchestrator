from __future__ import annotations

import json
import os
import time
from typing import Any

from .agent_eval import AgentProposal, AgentUsage


REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "diagnosis": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "repairs": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "strategy": {"type": "string", "enum": ["replace_text", "append_line", "remove_line"]},
                    "target_path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                    "line": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["strategy", "target_path", "old", "new", "line", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["diagnosis", "confidence", "repairs"],
    "additionalProperties": False,
}


class OpenAIAgentBackend:
    """Live provider backend using the OpenAI Responses API.

    The model only proposes allowlisted structured file operations. Execution
    remains inside the existing disposable sandbox and evaluator.
    """

    def __init__(self, model: str | None = None):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install the 'openai' extra to use the live backend") from exc
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-5.6")
        self.client = OpenAI()

    def propose(self, case: dict) -> AgentProposal:
        safe_case = {
            "id": case.get("id"),
            "initial_files": case.get("initial_files", {}),
        }
        started = time.perf_counter()
        response = self.client.responses.create(
            model=self.model,
            instructions=(
                "Diagnose the failing mini-repository and propose the smallest safe repair. "
                "Use only the allowed structured operations. Do not modify tests merely to make them pass. "
                "Do not propose shell commands, network access, dependency installation, secrets access, or workflow edits."
            ),
            input=json.dumps(safe_case, sort_keys=True),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ci_repair_proposal",
                    "strict": True,
                    "schema": REPAIR_SCHEMA,
                }
            },
        )
        latency = time.perf_counter() - started
        payload = json.loads(response.output_text)
        candidates = []
        for candidate in payload.get("repairs", []):
            strategy = candidate["strategy"]
            cleaned = {
                "strategy": strategy,
                "target_path": candidate["target_path"],
                "description": candidate["description"],
            }
            if strategy == "replace_text":
                cleaned.update(old=candidate["old"], new=candidate["new"])
            else:
                cleaned["line"] = candidate["line"]
            candidates.append(cleaned)

        usage = response.usage
        return AgentProposal(
            candidates=tuple(candidates),
            usage=AgentUsage(
                model=response.model,
                input_tokens=int(usage.input_tokens),
                output_tokens=int(usage.output_tokens),
                token_source="provider_reported",
                cost_usd=0.0,
                cost_source="not_computed_use_provider_billing_export",
                latency_seconds=round(latency, 6),
            ),
        )

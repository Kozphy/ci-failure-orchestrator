"""Model providers for the LLM baselines (B1, B2, B4). No vendor is hard-wired.

* ``none``     - does not call anything; every request is NOT_RUN with a reason. Default.
* ``mock``     - deterministic keyword heuristic used to exercise the pipeline in smoke runs and tests.
                 It is not a language model; its outputs are never claim-eligible.
* ``recorded`` - replays responses from a JSONL file keyed by request digest (reproducible re-analysis).
* ``command``  - runs an operator-supplied command with the prompt on stdin and reads one JSON object
                 from stdout. The command comes from an environment variable, runs without a shell and
                 with an allowlisted environment, and its output is parsed as data, never executed.

Only ``recorded`` and ``command`` responses are claim-eligible, and only when the run manifest records
the model name and version.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from ci_failure_orchestrator.service.common import DEFAULT_ENV_ALLOWLIST, split_command

from .taxonomy import CONFIDENCE_LEVELS, FAILURE_CATEGORIES, RECOMMENDED_ACTIONS

COMMAND_ENV_VAR = "CI_ORCHESTRATOR_RESEARCH_LLM_CMD"
MAX_RESPONSE_CHARS = 20_000

OK = "ok"
NOT_RUN = "not_run"
FAILED = "error"


@dataclass(frozen=True)
class LLMRequest:
    """One prompt sent to a provider."""

    system: str
    case_id: str
    prompt_id: str
    prompt_sha256: str
    prompt: str

    @property
    def digest(self) -> str:
        """Stable key for recordings: system, case, prompt version and the exact prompt text."""
        payload = f"{self.system}\n{self.case_id}\n{self.prompt_id}\n{self.prompt_sha256}\n{self.prompt}"
        return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LLMResponse:
    """Provider output; token counts and cost are None unless the provider reports them."""

    status: str
    text: str | None
    reason: str
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return asdict(self)


class Provider(Protocol):
    """A source of model responses."""

    name: str
    claim_eligible: bool

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return the response to ``request``."""
        ...


class NoneProvider:
    """Never calls a model; LLM baselines are reported NOT_RUN."""

    name = "none"
    claim_eligible = False

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return NOT_RUN."""
        del request
        return LLMResponse(NOT_RUN, None, "no model provider configured (provider: none)")


_MOCK_RULES: tuple[tuple[str, str, str], ...] = (
    ("secret", "security_or_policy", "block_and_escalate"),
    ("modulenotfounderror", "dependency", "repair_dependency"),
    ("resolutionimpossible", "dependency", "repair_dependency"),
    ("no space left", "infrastructure_or_environment", "investigate_infrastructure"),
    ("timed out", "timeout_or_resource", "retry_or_quarantine"),
    ("syntaxerror", "compilation_or_syntax", "repair_code"),
    ("error:", "compilation_or_syntax", "repair_code"),
    ("assert", "unit_test", "repair_code"),
)


class MockProvider:
    """Deterministic keyword heuristic standing in for a model in smoke runs. Not an LLM."""

    name = "mock"
    claim_eligible = False

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a schema-valid JSON prediction derived from keywords in the prompt."""
        text = request.prompt.lower()
        category, action = "other", "escalate_to_human"
        for needle, cat, act in _MOCK_RULES:
            if needle in text:
                category, action = cat, act
                break
        stages = [line.split(":", 1)[1].strip() for line in request.prompt.splitlines() if line.startswith("stage:")]
        payload = {
            "predicted_failure_class": category,
            "predicted_root_cause": stages[0] if stages else "unknown",
            "confidence": "low",
            "evidence": [f"mock keyword match: {category}"],
            "recommended_action": action,
        }
        return LLMResponse(OK, json.dumps(payload), "mock provider (not a language model)", latency_ms=0)


class RecordedProvider:
    """Replays responses recorded from an earlier ``command`` run."""

    name = "recorded"
    claim_eligible = True

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.responses: dict[str, dict[str, Any]] = {}
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.responses[str(row["digest"])] = row

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return the recorded response, or an error when none exists for this exact request."""
        row = self.responses.get(request.digest)
        if row is None:
            return LLMResponse(FAILED, None, f"no recording for request digest {request.digest[:12]}")
        response = row["response"]
        return LLMResponse(**{**response, "reason": f"recorded:{self.path.name}"})


class CommandProvider:
    """Runs an operator-supplied model command; optional recording makes the run replayable."""

    name = "command"
    claim_eligible = True

    def __init__(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int = 300,
        env_passthrough: Sequence[str] = (),
        record_to: Path | None = None,
    ) -> None:
        if not argv:
            raise ValueError(f"command provider needs a command (set {COMMAND_ENV_VAR})")
        self.argv = tuple(argv)
        self.timeout_seconds = timeout_seconds
        self.env_passthrough = tuple(env_passthrough)
        self.record_to = Path(record_to) if record_to else None

    def _env(self) -> dict[str, str]:
        allowed = set(DEFAULT_ENV_ALLOWLIST) | set(self.env_passthrough)
        return {k: v for k, v in os.environ.items() if k in allowed}

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Run the command with the prompt on stdin; non-zero exit or timeout is an error response."""
        started = time.perf_counter()
        try:
            run = subprocess.run(
                list(self.argv), input=request.prompt, capture_output=True, text=True, encoding="utf-8",
                timeout=self.timeout_seconds, env=self._env(), check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            response = LLMResponse(FAILED, None, f"command failed: {type(exc).__name__}")
        else:
            latency = int((time.perf_counter() - started) * 1000)
            if run.returncode != 0:
                response = LLMResponse(FAILED, None, f"command exited {run.returncode}", latency_ms=latency)
            else:
                response = LLMResponse(OK, run.stdout[:MAX_RESPONSE_CHARS], "command", latency_ms=latency)
        if self.record_to is not None:
            self.record_to.parent.mkdir(parents=True, exist_ok=True)
            with self.record_to.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({"digest": request.digest, "case_id": request.case_id,
                                         "system": request.system, "response": response.to_dict()},
                                        sort_keys=True) + "\n")
        return response


def build_provider(config: Mapping[str, Any]) -> Provider:
    """Build the provider named in the ``model`` section of an experiment config."""
    kind = str(config.get("provider") or "none")
    if kind == "none":
        return NoneProvider()
    if kind == "mock":
        return MockProvider()
    if kind == "recorded":
        path = config.get("recording")
        if not path:
            raise ValueError("recorded provider needs model.recording (a JSONL file)")
        return RecordedProvider(Path(str(path)))
    if kind == "command":
        raw = os.environ.get(str(config.get("command_env") or COMMAND_ENV_VAR), "")
        return CommandProvider(
            split_command(raw) if raw.strip() else (),
            timeout_seconds=int(config.get("timeout_seconds", 300)),
            env_passthrough=tuple(config.get("env_passthrough") or ()),
            record_to=Path(str(config["record_to"])) if config.get("record_to") else None,
        )
    raise ValueError(f"unknown model provider {kind!r}; choose none, mock, recorded or command")


@dataclass(frozen=True)
class ParsedPrediction:
    """A strictly validated model prediction; ``errors`` is non-empty when the output is invalid."""

    predicted_failure_class: str | None
    predicted_root_cause: str | None
    confidence: str | None
    evidence: list[str]
    recommended_action: str | None
    errors: list[str]


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


def parse_prediction(text: str | None, stages: Sequence[str] = ()) -> ParsedPrediction:
    """Validate a response against the strict prediction schema. Invalid output is never repaired."""
    errors: list[str] = []
    try:
        data = _extract_json(text or "")
    except (ValueError, json.JSONDecodeError) as exc:
        return ParsedPrediction(None, None, None, [], None, [f"unparseable:{exc}"])
    if not isinstance(data, dict):
        return ParsedPrediction(None, None, None, [], None, ["not_an_object"])
    expected = {"predicted_failure_class", "predicted_root_cause", "confidence", "evidence", "recommended_action"}
    missing = sorted(expected - set(data))
    extra = sorted(set(data) - expected)
    errors += [f"missing:{k}" for k in missing] + [f"unexpected:{k}" for k in extra]
    category = data.get("predicted_failure_class")
    if category not in FAILURE_CATEGORIES:
        errors.append("invalid:predicted_failure_class")
    confidence = data.get("confidence")
    if confidence not in CONFIDENCE_LEVELS:
        errors.append("invalid:confidence")
    action = data.get("recommended_action")
    if action not in RECOMMENDED_ACTIONS:
        errors.append("invalid:recommended_action")
    root = data.get("predicted_root_cause")
    if not isinstance(root, str) or not root.strip():
        errors.append("invalid:predicted_root_cause")
    elif stages and root.strip() not in stages:
        errors.append("invalid:predicted_root_cause_not_a_stage")
    evidence = data.get("evidence")
    if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
        errors.append("invalid:evidence")
        evidence = []
    return ParsedPrediction(
        category if category in FAILURE_CATEGORIES else None,
        root.strip() if isinstance(root, str) else None,
        confidence if confidence in CONFIDENCE_LEVELS else None,
        list(evidence)[:10],
        action if action in RECOMMENDED_ACTIONS else None,
        errors,
    )

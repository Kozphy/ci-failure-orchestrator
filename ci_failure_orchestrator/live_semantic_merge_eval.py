from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import median
from typing import Protocol

from .merge_conflict_agent import SemanticResolution


class TelemetrySemanticProvider(Protocol):
    last_latency_seconds: float
    last_input_tokens: int
    last_output_tokens: int

    def resolve_conflict(
        self,
        *,
        path: str,
        ours: str,
        theirs: str,
        hypothesis: str,
        proposed_change: str,
    ) -> SemanticResolution:
        ...


@dataclass(frozen=True)
class LiveSemanticRun:
    case_id: str
    trial: int
    accepted: bool
    verified: bool
    unsafe: bool
    confidence: float
    latency_seconds: float
    input_tokens: int
    output_tokens: int
    resolved_text: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LiveSemanticMetrics:
    runs: int
    verified_resolution_rate: float
    unsafe_resolution_rate: float
    escalation_rate: float
    p50_latency_seconds: float
    p95_latency_seconds: float
    mean_input_tokens: float
    mean_output_tokens: float
    total_tokens: int

    def to_dict(self) -> dict:
        return asdict(self)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return float(ordered[index])


def run_live_semantic_case(
    case: dict,
    provider: TelemetrySemanticProvider,
    *,
    trial: int,
    min_confidence: float = 0.80,
    max_resolved_chars: int = 20_000,
) -> LiveSemanticRun:
    result = provider.resolve_conflict(
        path=case["path"],
        ours=case["ours"],
        theirs=case["theirs"],
        hypothesis="resolve the held-out merge conflict without weakening safety semantics",
        proposed_change="preserve compatible intent from both sides with the smallest safe resolution",
    )
    text = result.resolved_text
    marker_present = any(marker in text for marker in ("<<<<<<<", "=======", ">>>>>>>"))
    unsafe = (
        not text.strip()
        or len(text) > max_resolved_chars
        or marker_present
        or any(fragment in text for fragment in case.get("forbidden_fragments", []))
    )
    accepted = result.confidence >= min_confidence and not unsafe
    verified = accepted and all(
        fragment in text for fragment in case.get("required_fragments", [])
    )
    return LiveSemanticRun(
        case_id=case["id"],
        trial=trial,
        accepted=accepted,
        verified=verified,
        unsafe=unsafe,
        confidence=float(result.confidence),
        latency_seconds=float(getattr(provider, "last_latency_seconds", 0.0)),
        input_tokens=int(getattr(provider, "last_input_tokens", 0)),
        output_tokens=int(getattr(provider, "last_output_tokens", 0)),
        resolved_text=text,
    )


def summarize_live_semantic_runs(runs: list[LiveSemanticRun]) -> LiveSemanticMetrics:
    if not runs:
        return LiveSemanticMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
    count = len(runs)
    latencies = [run.latency_seconds for run in runs]
    input_tokens = sum(run.input_tokens for run in runs)
    output_tokens = sum(run.output_tokens for run in runs)
    return LiveSemanticMetrics(
        runs=count,
        verified_resolution_rate=round(sum(run.verified for run in runs) / count, 4),
        unsafe_resolution_rate=round(sum(run.unsafe for run in runs) / count, 4),
        escalation_rate=round(sum(not run.accepted for run in runs) / count, 4),
        p50_latency_seconds=round(median(latencies), 4),
        p95_latency_seconds=round(_percentile(latencies, 0.95), 4),
        mean_input_tokens=round(input_tokens / count, 2),
        mean_output_tokens=round(output_tokens / count, 2),
        total_tokens=input_tokens + output_tokens,
    )

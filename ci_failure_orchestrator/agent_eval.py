from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Protocol

from .repair import RepairPlan, SandboxRepairExecutor


@dataclass(frozen=True)
class AgentUsage:
    model: str
    input_tokens: int
    output_tokens: int
    token_source: str
    cost_usd: float
    cost_source: str
    latency_seconds: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AgentProposal:
    candidates: tuple[dict, ...]
    usage: AgentUsage


class AgentBackend(Protocol):
    def propose(self, case: dict) -> AgentProposal: ...


class ReplayAgentBackend:
    """Reproducible agent-shaped backend for CI evaluation.

    It replays fixture repair candidates and estimates token volume from the
    serialized task. It makes no external model call, so cost is explicitly
    zero and must not be reported as real-model cost/performance.
    """

    def __init__(self, model: str = "replay-agent-v1"):
        self.model = model

    def propose(self, case: dict) -> AgentProposal:
        prompt_text = str({k: v for k, v in case.items() if k != "repair_candidates"})
        output_text = str(case.get("repair_candidates", []))
        input_tokens = max(1, len(prompt_text) // 4)
        output_tokens = max(1, len(output_text) // 4)
        return AgentProposal(
            candidates=tuple(case.get("repair_candidates", [])),
            usage=AgentUsage(
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                token_source="estimated_replay",
                cost_usd=0.0,
                cost_source="no_external_model_call",
                latency_seconds=0.0,
            ),
        )


@dataclass(frozen=True)
class AgentCaseResult:
    case_id: str
    resolved: bool
    attempts: int
    regression_detected: bool
    usage: AgentUsage

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AgentEvalMetrics:
    cases: int
    repair_success_rate: float
    regression_rate: float
    mean_attempts: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost_usd: float
    cost_per_success_usd: float
    p50_latency_seconds: float
    p95_latency_seconds: float

    def to_dict(self) -> dict:
        return asdict(self)


def run_agent_case(
    fixture_dir: Path,
    case: dict,
    backend: AgentBackend,
    executor: SandboxRepairExecutor,
    retry_budget: int = 2,
) -> AgentCaseResult:
    proposal = backend.propose(case)
    agent_case = dict(case)
    agent_case["repair_candidates"] = list(proposal.candidates)

    attempts = 0
    regression = False
    resolved = False
    for candidate in proposal.candidates[: max(retry_budget, 0)]:
        plan = RepairPlan(
            strategy=candidate["strategy"],
            target_path=candidate["target_path"],
            description=candidate.get("description", candidate["strategy"]),
        )
        attempt = executor.run(fixture_dir, agent_case, plan)
        attempts += 1
        regression = regression or attempt.regression_detected
        if attempt.success and not attempt.regression_detected:
            resolved = True
            break

    return AgentCaseResult(
        case_id=case["id"],
        resolved=resolved,
        attempts=attempts,
        regression_detected=regression and not resolved,
        usage=proposal.usage,
    )


def summarize_agent_results(results: list[AgentCaseResult]) -> AgentEvalMetrics:
    if not results:
        return AgentEvalMetrics(0, 0.0, 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0)

    successes = sum(result.resolved for result in results)
    input_tokens = sum(result.usage.input_tokens for result in results)
    output_tokens = sum(result.usage.output_tokens for result in results)
    total_cost = sum(result.usage.cost_usd for result in results)
    latencies = sorted(result.usage.latency_seconds for result in results)

    def percentile(values: list[float], q: float) -> float:
        index = min(len(values) - 1, round((len(values) - 1) * q))
        return round(values[index], 6)

    return AgentEvalMetrics(
        cases=len(results),
        repair_success_rate=round(successes / len(results), 4),
        regression_rate=round(sum(result.regression_detected for result in results) / len(results), 4),
        mean_attempts=round(mean(result.attempts for result in results), 4),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        total_cost_usd=round(total_cost, 6),
        cost_per_success_usd=round(total_cost / successes, 6) if successes else 0.0,
        p50_latency_seconds=percentile(latencies, 0.50),
        p95_latency_seconds=percentile(latencies, 0.95),
    )

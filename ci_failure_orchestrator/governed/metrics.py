"""Lightweight counters for governed pipeline observability."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PipelineMetrics:
    agent_runs_total: int = 0
    agent_runs_success_total: int = 0
    agent_runs_escalated_total: int = 0
    repair_attempts_total: int = 0
    tool_call_failures: int = 0
    sandbox_failures: int = 0
    evaluation_failures: int = 0
    policy_rejection_total: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    def record_latency(self, ms: float) -> None:
        self.latencies_ms.append(ms)

    def as_dict(self) -> dict[str, float | int]:
        success_rate = (
            0.0
            if self.agent_runs_total == 0
            else self.agent_runs_success_total / self.agent_runs_total
        )
        return {
            "agent_runs_total": self.agent_runs_total,
            "agent_runs_success_total": self.agent_runs_success_total,
            "agent_runs_escalated_total": self.agent_runs_escalated_total,
            "repair_attempts_total": self.repair_attempts_total,
            "repair_success_rate": success_rate,
            "tool_call_failures": self.tool_call_failures,
            "sandbox_failures": self.sandbox_failures,
            "evaluation_failures": self.evaluation_failures,
            "policy_rejection_rate": (
                0.0
                if self.agent_runs_total == 0
                else self.policy_rejection_total / self.agent_runs_total
            ),
            "human_escalation_rate": (
                0.0
                if self.agent_runs_total == 0
                else self.agent_runs_escalated_total / self.agent_runs_total
            ),
        }

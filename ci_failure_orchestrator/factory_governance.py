from __future__ import annotations

from dataclasses import dataclass, field

from .software_factory import FactoryTask


@dataclass
class RiskBasedGovernance:
    """Simple risk gate for autonomous execution.

    Low-risk work can proceed automatically. Higher-risk work is blocked until
    a future approval adapter explicitly authorizes it.
    """

    autonomous_risks: set[str] = field(default_factory=lambda: {"low"})

    def allow_autonomous_progress(self, task: FactoryTask) -> bool:
        return task.risk.lower() in self.autonomous_risks

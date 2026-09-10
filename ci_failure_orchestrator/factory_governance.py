"""Risk-based autonomy policy for software-factory task execution.

Governance is intentionally separate from agent execution and evaluation. A
worker may be capable of performing a task and an evaluator may be able to
verify it, but neither condition grants permission to proceed autonomously.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .software_factory import FactoryTask


@dataclass
class RiskBasedGovernance:
    """Allow autonomous progress only for explicitly approved risk classes.

    The default is deliberately conservative: only ``low`` risk work may run
    without an external approval path. Higher-risk tasks remain blocked until a
    future approval adapter or policy update explicitly authorizes them.
    """

    autonomous_risks: set[str] = field(default_factory=lambda: {"low"})

    def allow_autonomous_progress(self, task: FactoryTask) -> bool:
        """Return whether ``task`` may continue without human approval."""
        return task.risk.lower() in self.autonomous_risks

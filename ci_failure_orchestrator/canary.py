from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class CanaryResult:
    deployed: bool
    healthy: bool
    rolled_back: bool
    reason: str


class CanaryController:
    """Small execution boundary for canary deploy/health/rollback hooks."""

    def __init__(
        self,
        deploy: Callable[[], bool],
        health_check: Callable[[], bool],
        rollback: Callable[[], bool],
    ):
        self.deploy = deploy
        self.health_check = health_check
        self.rollback = rollback

    def run(self) -> CanaryResult:
        if not self.deploy():
            return CanaryResult(False, False, False, "canary deployment failed")
        if self.health_check():
            return CanaryResult(True, True, False, "canary healthy")
        rolled_back = self.rollback()
        return CanaryResult(
            True,
            False,
            rolled_back,
            "canary unhealthy; rollback executed" if rolled_back else "canary unhealthy; rollback failed",
        )

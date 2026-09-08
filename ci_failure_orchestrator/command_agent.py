from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess
import time
from typing import Sequence

from .agent_executor import PatchProposal
from .repair_planner import RepairPlan


@dataclass(frozen=True)
class CommandTelemetry:
    latency_ms: int
    returncode: int
    stdout_bytes: int
    stderr_bytes: int


class CommandCodingAgent:
    """Provider-neutral adapter for coding-agent CLIs.

    The repair plan is serialized to JSON and sent on stdin. The command must return
    a JSON object on stdout with: summary, changed_files, patch, and optional
    confidence. No shell is used, so callers must provide an explicit argv sequence.
    """

    def __init__(
        self,
        name: str,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        timeout_seconds: float = 120.0,
        env: dict[str, str] | None = None,
    ) -> None:
        if not argv:
            raise ValueError("argv must not be empty")
        self.name = name
        self.argv = tuple(argv)
        self.cwd = cwd
        self.timeout_seconds = timeout_seconds
        self.env = env
        self.last_telemetry: CommandTelemetry | None = None

    def propose_patch(self, plan: RepairPlan) -> PatchProposal:
        payload = json.dumps(plan.to_dict(), sort_keys=True).encode("utf-8")
        started = time.perf_counter()
        completed = subprocess.run(
            self.argv,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            env=self.env,
            timeout=self.timeout_seconds,
            shell=False,
            check=False,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        self.last_telemetry = CommandTelemetry(
            latency_ms=latency_ms,
            returncode=completed.returncode,
            stdout_bytes=len(completed.stdout),
            stderr_bytes=len(completed.stderr),
        )
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace")[-1000:]
            raise RuntimeError(f"coding agent exited with {completed.returncode}: {stderr}")

        try:
            result = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("coding agent did not return valid JSON") from exc

        return PatchProposal(
            provider=self.name,
            summary=str(result.get("summary", "")),
            changed_files=tuple(str(path) for path in result.get("changed_files", [])),
            patch=str(result.get("patch", "")),
            confidence=float(result.get("confidence", 0.5)),
            metadata={"adapter": self.__class__.__name__},
        )

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class WorkflowJobSnapshot:
    id: int
    name: str
    status: str
    conclusion: str | None
    needs: tuple[str, ...] = ()
    logs: str = ""


class GitHubActionsCollector:
    """Provider-neutral collector around GitHub Actions API callables.

    Network access is injected so the orchestration layer stays testable and does
    not embed authentication or GitHub SDK details.
    """

    def __init__(
        self,
        fetch_jobs: Callable[[int], list[dict[str, Any]]],
        fetch_logs: Callable[[int], str],
    ):
        self.fetch_jobs = fetch_jobs
        self.fetch_logs = fetch_logs

    def collect_failed_jobs(self, run_id: int) -> tuple[WorkflowJobSnapshot, ...]:
        snapshots: list[WorkflowJobSnapshot] = []
        for job in self.fetch_jobs(run_id):
            conclusion = job.get("conclusion")
            if conclusion not in {"failure", "cancelled", "timed_out"}:
                continue
            job_id = int(job["id"])
            snapshots.append(
                WorkflowJobSnapshot(
                    id=job_id,
                    name=str(job.get("name", job_id)),
                    status=str(job.get("status", "unknown")),
                    conclusion=str(conclusion) if conclusion is not None else None,
                    needs=tuple(str(value) for value in job.get("needs", []) or []),
                    logs=self.fetch_logs(job_id),
                )
            )
        return tuple(snapshots)

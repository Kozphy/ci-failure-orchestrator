from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .control_plane import ControlPlaneRun, RunStatus


class ControlPlaneAPI:
    """Dependency-free operator API contract for control-plane runs."""

    def __init__(self, runs: dict[str, ControlPlaneRun] | None = None) -> None:
        self.runs = runs or {}

    def register(self, run_id: str, run: ControlPlaneRun) -> None:
        self.runs[run_id] = run

    def _get(self, run_id: str) -> ControlPlaneRun:
        try:
            return self.runs[run_id]
        except KeyError as exc:
            raise KeyError(f"unknown run_id: {run_id}") from exc

    def list_runs(self) -> list[dict[str, Any]]:
        return [self._serialize(run_id, run) for run_id, run in self.runs.items()]

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._serialize(run_id, self._get(run_id))

    def get_failure_graph(self, run_id: str) -> dict[str, Any]:
        run = self._get(run_id)
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        if run.root_cause:
            nodes.append({"id": "root-cause", "kind": "root_cause", "label": run.root_cause})
        if run.plan is not None:
            if not nodes:
                nodes.append({
                    "id": "root-cause",
                    "kind": "root_cause",
                    "label": run.plan.hypothesis,
                    "confidence": run.plan.confidence,
                    "risk": run.plan.risk_score,
                })
            for index, step in enumerate(run.plan.steps, start=1):
                step_id = f"step-{index}"
                nodes.append({"id": step_id, "kind": "repair_step", "label": step})
                source = "root-cause" if index == 1 else f"step-{index - 1}"
                edges.append({"source": source, "target": step_id})
        return {"run_id": run_id, "incident_id": run.incident_id, "nodes": nodes, "edges": edges}

    def get_telemetry(self, run_id: str) -> dict[str, Any]:
        return self._get(run_id).telemetry()

    def get_approval_queue(self) -> list[dict[str, Any]]:
        queue: list[dict[str, Any]] = []
        for run_id, run in self.runs.items():
            if run.status == RunStatus.AWAITING_APPROVAL and run.approval is not None:
                queue.append({
                    "run_id": run_id,
                    "incident_id": run.incident_id,
                    "status": run.status.value,
                    "approval": asdict(run.approval),
                    "repair_plan": asdict(run.plan) if run.plan else None,
                })
        return queue

    def decide_approval(self, run_id: str, approved: bool, reviewer: str) -> dict[str, Any]:
        run = self._get(run_id)
        if run.approval is None or not run.approval.required:
            raise ValueError("run does not require human approval")
        run.approval.approved = approved
        run.approval.reviewer = reviewer
        run.status = RunStatus.DEPLOYING if approved else RunStatus.FAILED
        return self._serialize(run_id, run)

    def get_production_evidence(self, run_id: str) -> dict[str, Any] | None:
        run = self._get(run_id)
        return asdict(run.evidence) if run.evidence else None

    @staticmethod
    def _serialize(run_id: str, run: ControlPlaneRun) -> dict[str, Any]:
        payload = run.to_dict()
        payload["run_id"] = run_id
        return payload

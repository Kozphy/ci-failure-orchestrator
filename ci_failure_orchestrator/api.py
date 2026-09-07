from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .control_plane import ControlPlane, RunStatus


class ControlPlaneAPI:
    """Framework-agnostic API facade for the operator control plane.

    This keeps the core orchestration package dependency-free while exposing
    stable JSON-serializable contracts that can be mounted behind FastAPI,
    Flask, a serverless handler, or a WebSocket gateway later.
    """

    def __init__(self, control_plane: ControlPlane) -> None:
        self.control_plane = control_plane

    def list_runs(self) -> list[dict[str, Any]]:
        return [run.to_dict() for run in self.control_plane.runs.values()]

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.control_plane.get_run(run_id).to_dict()

    def get_failure_graph(self, run_id: str) -> dict[str, Any]:
        run = self.control_plane.get_run(run_id)
        plan = run.repair_plan
        nodes = []
        edges = []
        if plan is not None:
            root_id = "root-cause"
            nodes.append({
                "id": root_id,
                "kind": "root_cause",
                "label": plan.hypothesis,
                "confidence": plan.confidence,
                "risk": plan.risk_score,
            })
            for index, step in enumerate(plan.steps, start=1):
                step_id = f"step-{index}"
                nodes.append({"id": step_id, "kind": "repair_step", "label": step})
                edges.append({"source": root_id if index == 1 else f"step-{index-1}", "target": step_id})
        return {"run_id": run_id, "nodes": nodes, "edges": edges}

    def get_telemetry(self, run_id: str) -> dict[str, Any]:
        run = self.control_plane.get_run(run_id)
        telemetry = run.aggregate_telemetry()
        return asdict(telemetry)

    def get_approval_queue(self) -> list[dict[str, Any]]:
        queue: list[dict[str, Any]] = []
        for run in self.control_plane.runs.values():
            if run.status == RunStatus.WAITING_HUMAN and run.approval is not None:
                queue.append({
                    "run_id": run.run_id,
                    "incident_id": run.incident_id,
                    "status": run.status.value,
                    "approval": asdict(run.approval),
                    "repair_plan": asdict(run.repair_plan) if run.repair_plan else None,
                })
        return queue

    def decide_approval(self, run_id: str, approved: bool, actor: str, reason: str = "") -> dict[str, Any]:
        run = self.control_plane.get_run(run_id)
        self.control_plane.record_human_decision(run_id, approved=approved, actor=actor, reason=reason)
        return run.to_dict()

    def get_production_evidence(self, run_id: str) -> dict[str, Any] | None:
        run = self.control_plane.get_run(run_id)
        return asdict(run.production_evidence) if run.production_evidence else None

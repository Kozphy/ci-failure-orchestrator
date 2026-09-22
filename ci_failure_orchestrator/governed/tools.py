"""Typed tool registry with risk levels and JSON-serializable I/O."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .models import ToolCall, ToolResult, ToolRiskLevel, new_id, utc_now


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    timeout_seconds: float
    risk_level: ToolRiskLevel
    side_effect: str  # none | read | write | network


class ToolHandler(Protocol):
    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ...


class ToolRegistry:
    """Permissioned tool catalog. Handlers must not be arbitrary shell wrappers."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def get(self, name: str) -> ToolSpec:
        if name not in self._specs:
            raise KeyError(f"unknown tool: {name}")
        return self._specs[name]

    def list_tools(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs[name] for name in sorted(self._specs))

    def invoke(self, run_id: str, tool_name: str, arguments: dict[str, Any]) -> tuple[ToolCall, ToolResult]:
        spec = self.get(tool_name)
        call = ToolCall(
            call_id=new_id("call"),
            run_id=run_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            risk_level=spec.risk_level,
        )
        started = time.perf_counter()
        try:
            output = self._handlers[tool_name](arguments)
            ok = True
            error = None
        except Exception as exc:  # noqa: BLE001 - surfaced in ToolResult
            output = {}
            ok = False
            error = str(exc)
        duration_ms = (time.perf_counter() - started) * 1000.0
        if duration_ms > spec.timeout_seconds * 1000.0:
            ok = False
            error = error or f"tool exceeded timeout {spec.timeout_seconds}s"
        result = ToolResult(
            call_id=call.call_id,
            run_id=run_id,
            tool_name=tool_name,
            ok=ok,
            output=output,
            error=error,
            duration_ms=duration_ms,
            timestamp=utc_now(),
        )
        return call, result


def build_default_registry(
    *,
    log_reader: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    test_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    file_reader: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> ToolRegistry:
    """Register safe default tools used by the governed pipeline demos/tests."""

    registry = ToolRegistry()

    def _logs(args: dict[str, Any]) -> dict[str, Any]:
        excerpt = str(args.get("excerpt") or "")[:4000]
        return {"lines": excerpt.splitlines()[-50:], "count": excerpt.count("\n") + 1}

    def _tests(args: dict[str, Any]) -> dict[str, Any]:
        # Deterministic stub: callers inject real runners in production adapters.
        target = str(args.get("target") or "default")
        return {"target": target, "passed": bool(args.get("force_pass", True))}

    def _read(args: dict[str, Any]) -> dict[str, Any]:
        path = str(args.get("path") or "")
        if ".." in path.replace("\\", "/") or path.startswith("/"):
            raise ValueError("path traversal blocked")
        return {"path": path, "exists": False, "note": "inject file_reader for real IO"}

    registry.register(
        ToolSpec(
            name="log_inspection",
            description="Read bounded log excerpts for a failing job",
            input_schema={"type": "object", "properties": {"excerpt": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"lines": {"type": "array"}}},
            timeout_seconds=5.0,
            risk_level=ToolRiskLevel.READ_ONLY,
            side_effect="read",
        ),
        log_reader or _logs,
    )
    registry.register(
        ToolSpec(
            name="test_runner",
            description="Run an allowlisted target test selector",
            input_schema={"type": "object", "properties": {"target": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"passed": {"type": "boolean"}}},
            timeout_seconds=120.0,
            risk_level=ToolRiskLevel.RESTRICTED,
            side_effect="write",
        ),
        test_runner or _tests,
    )
    registry.register(
        ToolSpec(
            name="file_read",
            description="Read a repository-relative file within path policy",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            timeout_seconds=5.0,
            risk_level=ToolRiskLevel.READ_ONLY,
            side_effect="read",
        ),
        file_reader or _read,
    )
    return registry

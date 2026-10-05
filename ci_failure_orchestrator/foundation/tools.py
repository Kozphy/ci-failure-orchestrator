"""Typed tool registry and minimum useful tools."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .models import ToolCall, ToolResult, ToolRiskLevel, new_id, utc_now
from .sanitization import sanitize_text


class ToolValidationError(ValueError):
    """Invalid tool registration, lookup or arguments."""
    pass


class ToolExecutionError(RuntimeError):
    """Tool execution failure."""
    pass


@dataclass(frozen=True)
class ToolSpec:
    """Name, schemas, risk level, side effect and timeout of a tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: ToolRiskLevel
    side_effect: str
    timeout_seconds: float = 30.0


class Tool(Protocol):
    """Interface for a registered tool."""

    @property
    def spec(self) -> ToolSpec:
        """Static description of the tool."""
        ...

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Run the tool with the given arguments."""
        ...


@dataclass
class ToolRegistry:
    """Registry of tools keyed by unique name."""

    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        """Add a tool to the registry.

        Raises:
            ToolValidationError: If a tool with the same name is already registered.
        """

        name = tool.spec.name
        if name in self._tools:
            raise ToolValidationError(f"duplicate tool name: {name}")
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        """Return the named tool.

        Raises:
            ToolValidationError: If no tool has that name.
        """

        if name not in self._tools:
            raise ToolValidationError(f"unknown tool: {name}")
        return self._tools[name]

    def list_tools(self) -> tuple[ToolSpec, ...]:
        """Return the specs of all registered tools, sorted by name."""
        return tuple(self._tools[n].spec for n in sorted(self._tools))

    def invoke(self, run_id: str, tool_name: str, arguments: dict[str, Any]) -> tuple[ToolCall, ToolResult]:
        """Run a tool and return the call record with a bounded, sanitized result.

        An exception raised by the tool becomes a failed result. A run that exceeds the tool's timeout
        is reported as failed with exit code 124 after it finishes; it is not interrupted.

        Returns:
            The ``ToolCall`` record and the ``ToolResult``.

        Raises:
            ToolValidationError: If the tool is not registered.
        """

        tool = self.get(tool_name)
        call = ToolCall(
            call_id=new_id("call"),
            run_id=run_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            risk_level=tool.spec.risk_level,
        )
        started = time.perf_counter()
        try:
            result = tool.execute(arguments)
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - started) * 1000.0
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                exit_code=1,
                stderr=str(exc),
                metadata={"duration_ms": elapsed},
                call_id=call.call_id,
                run_id=run_id,
            )
            return call, result

        # Bound and sanitize outputs
        stdout, _ = sanitize_text((result.stdout or "")[:20_000])
        stderr, _ = sanitize_text((result.stderr or "")[:8_000])
        elapsed = (time.perf_counter() - started) * 1000.0
        if elapsed > tool.spec.timeout_seconds * 1000.0:
            return call, ToolResult(
                tool_name=tool_name,
                success=False,
                exit_code=124,
                stdout=stdout,
                stderr=stderr or f"timeout>{tool.spec.timeout_seconds}s",
                metadata={"duration_ms": elapsed, **(result.metadata or {})},
                call_id=call.call_id,
                run_id=run_id,
                timestamp=utc_now(),
            )
        return call, ToolResult(
            tool_name=tool_name,
            success=result.success,
            exit_code=result.exit_code,
            stdout=stdout,
            stderr=stderr,
            metadata={"duration_ms": elapsed, **(result.metadata or {})},
            call_id=call.call_id,
            run_id=run_id,
            timestamp=utc_now(),
        )


def _safe_relpath(path: str) -> str:
    normalized = path.replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        raise ToolValidationError(f"path out of scope: {path}")
    return normalized


class LogReadTool:
    """Read-only tool that returns the tail of a sanitized log excerpt."""

    @property
    def spec(self) -> ToolSpec:
        """Spec of the ``log_reader`` tool."""

        return ToolSpec(
            name="log_reader",
            description="Read a bounded log excerpt",
            input_schema={"type": "object", "properties": {"excerpt": {"type": "string"}}},
            output_schema={"type": "object"},
            risk_level=ToolRiskLevel.READ_ONLY,
            side_effect="none",
            timeout_seconds=5.0,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Return the last 80 sanitized lines of the ``excerpt`` argument."""

        excerpt = str(arguments.get("excerpt") or "")
        cleaned, _ = sanitize_text(excerpt)
        lines = cleaned.splitlines()[-80:]
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            stdout="\n".join(lines),
            metadata={"line_count": len(lines)},
        )


class FileReadTool:
    """Read-only tool that reads a repository-relative text file under a root directory."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root

    @property
    def spec(self) -> ToolSpec:
        """Spec of the ``file_reader`` tool."""

        return ToolSpec(
            name="file_reader",
            description="Read a repository-relative text file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            output_schema={"type": "object"},
            risk_level=ToolRiskLevel.READ_ONLY,
            side_effect="read",
            timeout_seconds=5.0,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Return up to 20,000 sanitized characters of the file named by the ``path`` argument.

        With no root configured, returns an empty successful result.

        Raises:
            ToolValidationError: If the path is empty, absolute, contains ``..`` or resolves outside the root.
        """

        rel = _safe_relpath(str(arguments.get("path") or ""))
        if self.root is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                stdout="",
                metadata={"path": rel, "exists": False, "note": "no_root_configured"},
            )
        path = (self.root / rel).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ToolValidationError("path escape blocked")
        if not path.exists() or not path.is_file():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                exit_code=1,
                stderr="file_not_found",
                metadata={"path": rel},
            )
        text = path.read_text(encoding="utf-8", errors="replace")[:20_000]
        cleaned, _ = sanitize_text(text)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            stdout=cleaned,
            metadata={"path": rel, "exists": True},
        )


class TestRunnerTool:
    """Allowlisted structured test runner (no free-form shell)."""

    def __init__(self, runner: Callable[[str], ToolResult] | None = None) -> None:
        self._runner = runner

    @property
    def spec(self) -> ToolSpec:
        """Spec of the ``test_runner`` tool."""

        return ToolSpec(
            name="test_runner",
            description="Run an allowlisted verification target",
            input_schema={"type": "object", "properties": {"target": {"type": "string"}}},
            output_schema={"type": "object"},
            risk_level=ToolRiskLevel.RESTRICTED,
            side_effect="write",
            timeout_seconds=120.0,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Run the ``target`` argument with the injected runner, or return a deterministic stub result."""

        target = str(arguments.get("target") or "targeted")
        if self._runner is not None:
            return self._runner(target)
        # Deterministic stub for foundation tests / demos.
        force_fail = bool(arguments.get("force_fail", False))
        return ToolResult(
            tool_name=self.spec.name,
            success=not force_fail,
            exit_code=1 if force_fail else 0,
            stdout=f"target={target} result={'FAIL' if force_fail else 'PASS'}",
            metadata={"target": target, "stub": True},
        )


class PatchApplyTool:
    """Validate and describe a patch application (used inside sandbox)."""

    @property
    def spec(self) -> ToolSpec:
        """Spec of the ``patch_apply`` tool."""

        return ToolSpec(
            name="patch_apply",
            description="Validate patch text and file list for sandbox apply",
            input_schema={
                "type": "object",
                "properties": {
                    "patch": {"type": "string"},
                    "files": {"type": "array"},
                },
            },
            output_schema={"type": "object"},
            risk_level=ToolRiskLevel.SAFE_WRITE,
            side_effect="write",
            timeout_seconds=10.0,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Validate the ``patch`` text and ``files`` paths without applying the patch.

        Raises:
            ToolValidationError: If a listed path is empty, absolute or contains ``..``.
        """

        patch = str(arguments.get("patch") or "")
        files = [str(f) for f in (arguments.get("files") or [])]
        if not patch.strip():
            return ToolResult(self.spec.name, False, 1, stderr="empty_patch")
        if "\x00" in patch:
            return ToolResult(self.spec.name, False, 1, stderr="binary_patch_rejected")
        for path in files:
            _safe_relpath(path)
        return ToolResult(
            self.spec.name,
            True,
            0,
            stdout="patch_validated",
            metadata={"files": files, "bytes": len(patch)},
        )


def build_default_registry(*, root: Path | None = None, test_runner: Callable[[str], ToolResult] | None = None) -> ToolRegistry:
    """Return a registry with the log reader, file reader, test runner and patch apply tools.

    Args:
        root: Root directory for the file reader; with None it returns empty results.
        test_runner: Runner for the test runner tool; with None it returns a deterministic stub result.
    """

    registry = ToolRegistry()
    registry.register(LogReadTool())
    registry.register(FileReadTool(root=root))
    registry.register(TestRunnerTool(runner=test_runner))
    registry.register(PatchApplyTool())
    return registry

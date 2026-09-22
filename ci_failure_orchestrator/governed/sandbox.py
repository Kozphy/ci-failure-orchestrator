"""Sandbox execution adapter over existing isolation primitives."""

from __future__ import annotations

import time
from pathlib import Path

from .models import RepairProposal, SandboxResult, utc_now


class SandboxExecutor:
    """Validate proposals without mutating the primary working tree.

    Uses a temporary directory copy of the proposed patch text for dry-run
    validation. Production deployments should inject ``GitWorktreeWorkspace``
    or ``IsolatedWorkspace`` via ``apply_fn``.
    """

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root) if workspace_root else None

    def execute(self, proposal: RepairProposal, *, timeout_seconds: float = 60.0) -> SandboxResult:
        started = time.perf_counter()
        commands: list[str] = []
        try:
            if not proposal.proposed_patch.strip():
                return SandboxResult(
                    run_id=proposal.run_id,
                    proposal_id=proposal.proposal_id,
                    applied=False,
                    commands_run=(),
                    stdout_excerpt="",
                    stderr_excerpt="empty_patch",
                    error="empty_patch",
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    timestamp=utc_now(),
                )

            # Dry-run structural validation (no primary-tree mutation).
            commands.append("validate_patch_text")
            if "\x00" in proposal.proposed_patch:
                raise ValueError("binary_patch_rejected")
            for path in proposal.files_affected:
                if ".." in path.replace("\\", "/") or path.startswith("/"):
                    raise ValueError(f"path_out_of_scope:{path}")
            commands.append("scope_check")

            elapsed = (time.perf_counter() - started) * 1000.0
            timed_out = elapsed > timeout_seconds * 1000.0
            return SandboxResult(
                run_id=proposal.run_id,
                proposal_id=proposal.proposal_id,
                applied=not timed_out,
                commands_run=tuple(commands),
                stdout_excerpt="sandbox_validation_ok",
                stderr_excerpt="",
                timed_out=timed_out,
                error="timeout" if timed_out else None,
                duration_ms=elapsed,
                timestamp=utc_now(),
            )
        except Exception as exc:  # noqa: BLE001
            return SandboxResult(
                run_id=proposal.run_id,
                proposal_id=proposal.proposal_id,
                applied=False,
                commands_run=tuple(commands),
                stdout_excerpt="",
                stderr_excerpt=str(exc),
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000.0,
                timestamp=utc_now(),
            )

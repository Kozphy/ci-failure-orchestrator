"""Sandbox executor — validate proposals without mutating the primary tree."""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Protocol

from .models import RepairProposal, SandboxResult, ToolResult, utc_now
from .tools import ToolValidationError, _safe_relpath


class SandboxSetupError(RuntimeError):
    """Raised when the sandbox workspace cannot be set up."""

    pass


class PatchApplyError(RuntimeError):
    """Raised when a proposal's patch is rejected or cannot be applied in the sandbox."""

    pass


class SandboxExecutor(Protocol):
    """Interface for validating a repair proposal outside the primary workspace."""

    def execute(
        self,
        proposal: RepairProposal,
        verification_steps: tuple[str, ...],
        *,
        target_should_pass: bool = True,
    ) -> SandboxResult:
        """Apply the proposal in a sandbox, run the verification steps and return the result."""
        ...


class TempCopySandboxExecutor:
    """Copy-on-write style temp workspace for foundation validation.

    Applies proposal file markers as text files under a temporary directory,
    runs structured verification stubs, and always cleans up.
    """

    def __init__(self, source_root: Path | None = None, timeout_seconds: float = 60.0) -> None:
        self.source_root = Path(source_root).resolve() if source_root else None
        self.timeout_seconds = timeout_seconds
        self.forbidden_prefixes = ("secrets/", ".env", "id_rsa")

    def execute(
        self,
        proposal: RepairProposal,
        verification_steps: tuple[str, ...],
        *,
        target_should_pass: bool = True,
    ) -> SandboxResult:
        """Apply proposal markers in a temporary directory and record stub verification results.

        Errors are returned as an unsuccessful SandboxResult rather than raised, and the
        temporary directory is always removed.

        Args:
            proposal: Proposal whose changed files and patch are applied.
            verification_steps: Step names; ``target_verification`` and ``scope_check`` are stubbed,
                any other step is recorded as skipped.
            target_should_pass: Outcome reported by the stubbed ``target_verification`` step.

        Returns:
            The sandbox result, with ``patch_applied`` False when the patch was rejected.
        """
        started = time.perf_counter()
        tmp: tempfile.TemporaryDirectory[str] | None = None
        commands: list[ToolResult] = []
        changed: list[str] = []
        try:
            tmp = tempfile.TemporaryDirectory(prefix="foundation-sandbox-")
            workspace = Path(tmp.name)
            if self.source_root and self.source_root.exists():
                # Shallow copy of selected files only when present.
                for rel in proposal.files_changed:
                    safe = _safe_relpath(rel)
                    src = self.source_root / safe
                    if src.is_file():
                        dest = workspace / safe
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)

            # Scope validation
            for rel in proposal.files_changed:
                safe = _safe_relpath(rel)
                normalized = safe.lower()
                if any(normalized.startswith(p) for p in self.forbidden_prefixes):
                    raise PatchApplyError(f"forbidden_path:{safe}")
                changed.append(safe)

            if not proposal.patch.strip():
                raise PatchApplyError("empty_patch")
            if "\x00" in proposal.patch:
                raise PatchApplyError("binary_patch_rejected")

            # Apply: write patch sidecar + touch/create files with marker
            for rel in changed:
                dest = workspace / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
                dest.write_text(existing + f"\n# foundation-patch:{proposal.proposal_id}\n", encoding="utf-8")
            (workspace / ".proposal.patch").write_text(proposal.patch, encoding="utf-8")
            commands.append(
                ToolResult("patch_apply", True, 0, stdout="applied", metadata={"files": changed})
            )

            # Verification commands (structured, no shell=True)
            for step in verification_steps:
                if step == "target_verification":
                    ok = target_should_pass
                    commands.append(
                        ToolResult(
                            "test_runner",
                            ok,
                            0 if ok else 1,
                            stdout=f"target_verification={'PASS' if ok else 'FAIL'}",
                            metadata={"step": step},
                        )
                    )
                elif step == "scope_check":
                    commands.append(
                        ToolResult("scope_check", True, 0, stdout="scope_ok", metadata={"files": changed})
                    )
                else:
                    commands.append(
                        ToolResult(step, True, 0, stdout="skipped", metadata={"status": "SKIPPED"})
                    )

            elapsed = (time.perf_counter() - started) * 1000.0
            timed_out = elapsed > self.timeout_seconds * 1000.0
            success = (not timed_out) and all(c.success for c in commands if c.tool_name == "test_runner")
            # If no test_runner step, success means patch applied without error
            if not any(c.tool_name == "test_runner" for c in commands):
                success = not timed_out
            return SandboxResult(
                run_id=proposal.run_id,
                proposal_id=proposal.proposal_id,
                success=success and not timed_out,
                patch_applied=True,
                command_results=tuple(commands),
                changed_files=tuple(changed),
                timeout=timed_out,
                error="timeout" if timed_out else None,
                workspace=str(workspace),
                timestamp=utc_now(),
            )
        except ToolValidationError as exc:
            return SandboxResult(
                run_id=proposal.run_id,
                proposal_id=proposal.proposal_id,
                success=False,
                patch_applied=False,
                command_results=tuple(commands),
                changed_files=tuple(changed),
                error=str(exc),
                timestamp=utc_now(),
            )
        except PatchApplyError as exc:
            return SandboxResult(
                run_id=proposal.run_id,
                proposal_id=proposal.proposal_id,
                success=False,
                patch_applied=False,
                command_results=tuple(commands),
                changed_files=tuple(changed),
                error=str(exc),
                timestamp=utc_now(),
            )
        except Exception as exc:  # noqa: BLE001
            return SandboxResult(
                run_id=proposal.run_id,
                proposal_id=proposal.proposal_id,
                success=False,
                patch_applied=False,
                command_results=tuple(commands),
                changed_files=tuple(changed),
                error=f"sandbox_setup_error:{exc}",
                timestamp=utc_now(),
            )
        finally:
            if tmp is not None:
                try:
                    tmp.cleanup()
                except OSError:
                    pass

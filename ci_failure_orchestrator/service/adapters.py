"""Foundation adapters: a real proposal factory and a git-worktree sandbox executor."""

from __future__ import annotations

import time
from hashlib import sha256

from ..foundation.models import (
    FailureClassification,
    RepairPlan,
    RepairProposal,
    SandboxResult,
    ToolResult,
    new_id,
    utc_now,
)
from ..foundation.persistence import FileEvidenceStore
from ..patch_sandbox import WorktreePatchVerifier
from .common import FIX_DIR, MAX_FEEDBACK_CHARS, tail
from .patches import extract_patch, is_unsafe_path, parse_patch_files, patch_violation
from .prompt import build_prompt, extract_rationale
from .proposals import ProposalSource
from .records import Attempt, AttemptStatus, write_attempt
from .session import FixSession
from .untrusted import clean_untrusted


class RepoFixProposalFactory:
    """ProposalFactory for the foundation runner backed by a real proposal source."""

    def __init__(self, session: FixSession, source: ProposalSource) -> None:
        self.session = session
        self.source = source
        self.evidence = FileEvidenceStore(session.artifacts_root)

    def __call__(
        self,
        *,
        run_id: str,
        plan: RepairPlan,
        classification: FailureClassification,
        attempt_number: int,
        paths: tuple[str, ...],
        force_forbidden_path: bool,
    ) -> RepairProposal:
        self.session.attempt_started_at = utc_now()
        self.session.attempt_started_clock = time.monotonic()
        prompt = build_prompt(self.session, attempt_number=attempt_number, changed_paths=paths)
        generated = self.source.generate(prompt, attempt_number)
        patch = extract_patch(generated.text)
        files = parse_patch_files(patch)
        self.session.last_error = generated.error or (None if patch else "no_patch_extracted")
        if self.source.name == "provider-cmd":
            self.evidence.write_text(run_id, FIX_DIR, prompt, name=f"attempt-{attempt_number:03d}-prompt.txt")
            response = generated.text + (f"\n\n[stderr]\n{generated.detail}" if generated.detail else "")
            self.evidence.write_text(run_id, FIX_DIR, response, name=f"attempt-{attempt_number:03d}-response.txt")
        rationale = extract_rationale(generated.text) or f"{self.source.name} proposal (attempt {attempt_number})"
        return RepairProposal(
            proposal_id=new_id("prop"),
            run_id=run_id,
            files_changed=files,
            patch=patch,
            rationale=rationale,
            expected_effect="All verification commands pass: " + "; ".join(c.display for c in self.session.commands),
            verification_plan=tuple(c.display for c in self.session.commands),
        )


class WorktreeSandbox:
    """SandboxExecutor that verifies a proposal in a disposable worktree of the target repo."""

    def __init__(self, session: FixSession, verifier: WorktreePatchVerifier) -> None:
        self.session = session
        self.verifier = verifier
        self.attempt = 0

    def _record(self, reason: str, output: str = "") -> None:
        self.session.feedback.append(
            {"attempt": self.attempt, "reason": reason, "output": tail(clean_untrusted(output), MAX_FEEDBACK_CHARS)}
        )

    def _attempt(self, proposal: RepairProposal, status: AttemptStatus, error: str | None) -> None:
        session = self.session
        started_clock = session.attempt_started_clock or time.monotonic()
        write_attempt(
            session.artifacts_root,
            Attempt(
                attempt_id=new_id("att"),
                task_id=session.task_id,
                run_id=proposal.run_id,
                number=self.attempt,
                agent=session.agent,
                proposal_source=session.proposal_source,
                status=status,
                error=error,
                patch_sha256=sha256(proposal.patch.encode("utf-8")).hexdigest() if proposal.patch.strip() else None,
                files_changed=proposal.files_changed,
                started_at=session.attempt_started_at or utc_now(),
                completed_at=utc_now(),
                duration_ms=int((time.monotonic() - started_clock) * 1000),
            ),
        )

    def execute(
        self,
        proposal: RepairProposal,
        verification_steps: tuple[str, ...],
        *,
        target_should_pass: bool = True,
    ) -> SandboxResult:
        self.attempt += 1
        if not proposal.patch.strip():
            error = self.session.last_error or "no_patch_extracted"
            self._record(error, "No unified diff was found in the response.")
            self._attempt(proposal, AttemptStatus.NO_PATCH, error)
            return SandboxResult(proposal.run_id, proposal.proposal_id, False, False, (), (), error=error, workspace="git-worktree")

        violation = patch_violation(proposal.patch)
        if violation is None and any(is_unsafe_path(p) for p in proposal.files_changed):
            violation = "forbidden_path_outside_repo"
        if violation:
            self._record(violation, "Patch refused before any worktree was created.")
            self._attempt(proposal, AttemptStatus.REFUSED, violation)
            return SandboxResult(
                proposal.run_id, proposal.proposal_id, False, False, (), proposal.files_changed,
                error=violation, workspace="git-worktree",
            )

        result = self.verifier.verify(
            repo_path=self.session.repo,
            patch_text=proposal.patch,
            base_ref=self.session.base_commit,
        )
        displays = {c.name: c.display for c in self.session.commands}
        command_results: list[ToolResult] = [
            ToolResult(
                tool_name=f"verify:{step.name}",
                success=step.passed,
                exit_code=step.returncode,
                stdout=step.stdout,
                stderr=step.stderr,
                metadata={"command": displays.get(step.name, step.name), "latency_ms": round(step.latency_ms, 1)},
            )
            for step in result.steps
        ]
        failing = next((s for s in result.steps if not s.passed), None)
        if result.applied:
            command_results.append(
                ToolResult(
                    tool_name="test_runner",
                    success=result.passed,
                    exit_code=0 if result.passed else (failing.returncode if failing else 1),
                    stdout=(
                        "all verification commands passed"
                        if result.passed
                        else f"failed: {displays.get(failing.name, failing.name) if failing else 'no commands'}"
                    ),
                    metadata={"steps": len(result.steps), "patch_sha256": result.patch_sha256},
                )
            )
        timeout = any(s.returncode == 124 and "verification_timeout" in s.stderr for s in result.steps)
        error = None if result.applied else (result.reason or "patch_apply_failed")

        if not result.applied:
            self._record(error, "git apply rejected the patch; context lines must match the base files exactly.")
            self._attempt(proposal, AttemptStatus.PATCH_REJECTED, error)
        elif not result.passed:
            label = displays.get(failing.name, failing.name) if failing else "verification"
            output = f"{failing.stdout}\n{failing.stderr}".strip() if failing else ""
            self._record(f"verification command failed: {label}", output)
            self._attempt(proposal, AttemptStatus.VERIFICATION_FAILED, f"verification command failed: {label}")
        else:
            self._attempt(proposal, AttemptStatus.VERIFIED, None)

        changed = tuple(dict.fromkeys((*result.changed_files, *proposal.files_changed)))
        return SandboxResult(
            run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            success=result.passed,
            patch_applied=result.applied,
            command_results=tuple(command_results),
            changed_files=changed,
            timeout=timeout,
            error=error,
            workspace="git-worktree",
        )

"""Deterministic failure injection — TEST/BENCHMARK ONLY."""

from __future__ import annotations

from pathlib import Path

from ..evaluator import Evaluator
from ..models import (
    CheckStatus,
    EvaluationCheck,
    EvaluationResult,
    RepairProposal,
    SandboxResult,
    ToolResult,
)
from ..sandbox import SandboxExecutor
from .schemas import FailureInjectionSpec


class BenchmarkInjectionError(RuntimeError):
    """Raised when injection is requested without benchmark_mode."""


class InjectingSandbox:
    """Wraps a sandbox and injects a single deterministic failure."""

    def __init__(
        self,
        inner: SandboxExecutor,
        *,
        spec: FailureInjectionSpec,
        benchmark_mode: bool,
    ) -> None:
        if not benchmark_mode:
            raise BenchmarkInjectionError(
                "Failure injection requires benchmark_mode=True"
            )
        if spec.target != "sandbox":
            raise BenchmarkInjectionError(f"InjectingSandbox got target={spec.target}")
        self._inner = inner
        self._spec = spec
        self._hits = 0

    def execute(
        self,
        proposal: RepairProposal,
        verification_steps: tuple[str, ...],
        *,
        target_should_pass: bool = True,
    ) -> SandboxResult:
        self._hits += 1
        if self._hits == self._spec.occurrence:
            if self._spec.failure == "timeout":
                return SandboxResult(
                    run_id=proposal.run_id,
                    proposal_id=proposal.proposal_id,
                    success=False,
                    patch_applied=False,
                    command_results=(),
                    changed_files=(),
                    timeout=True,
                    error="benchmark_injected_timeout",
                )
            if self._spec.failure in {"error", "setup_failure"}:
                return SandboxResult(
                    run_id=proposal.run_id,
                    proposal_id=proposal.proposal_id,
                    success=False,
                    patch_applied=False,
                    command_results=(),
                    changed_files=(),
                    error="benchmark_injected_sandbox_error",
                )
            if self._spec.failure == "patch_failure":
                return SandboxResult(
                    run_id=proposal.run_id,
                    proposal_id=proposal.proposal_id,
                    success=False,
                    patch_applied=False,
                    command_results=(
                        ToolResult(
                            tool_name="patch",
                            success=False,
                            exit_code=1,
                            stderr="benchmark_injected_patch_failure",
                        ),
                    ),
                    changed_files=(),
                    error="benchmark_injected_patch_failure",
                )
        return self._inner.execute(
            proposal,
            verification_steps,
            target_should_pass=target_should_pass,
        )


class InjectingEvaluator:
    def __init__(
        self,
        inner: Evaluator,
        *,
        spec: FailureInjectionSpec,
        benchmark_mode: bool,
    ) -> None:
        if not benchmark_mode:
            raise BenchmarkInjectionError(
                "Failure injection requires benchmark_mode=True"
            )
        if spec.target != "evaluator":
            raise BenchmarkInjectionError(f"InjectingEvaluator got target={spec.target}")
        self._inner = inner
        self._spec = spec
        self._hits = 0

    def evaluate(
        self,
        *,
        proposal: RepairProposal,
        sandbox: SandboxResult,
    ) -> EvaluationResult:
        self._hits += 1
        if self._hits == self._spec.occurrence and self._spec.failure in {
            "error",
            "eval_failure",
        }:
            return EvaluationResult(
                run_id=proposal.run_id,
                passed=False,
                patch_applied=False,
                target_verification_passed=False,
                regressions_detected=False,
                forbidden_changes_detected=False,
                checks=(
                    EvaluationCheck(
                        "PATCH_APPLIED",
                        CheckStatus.FAILED,
                        "benchmark_injected_eval_failure",
                    ),
                ),
                evidence=("benchmark_injected_eval_failure",),
            )
        return self._inner.evaluate(proposal=proposal, sandbox=sandbox)


def maybe_wrap_sandbox(
    sandbox: SandboxExecutor,
    injection: FailureInjectionSpec | None,
    *,
    benchmark_mode: bool,
) -> SandboxExecutor:
    if injection is None or injection.target != "sandbox":
        return sandbox
    return InjectingSandbox(sandbox, spec=injection, benchmark_mode=benchmark_mode)


def maybe_wrap_evaluator(
    evaluator: Evaluator,
    injection: FailureInjectionSpec | None,
    *,
    benchmark_mode: bool,
) -> Evaluator:
    if injection is None or injection.target != "evaluator":
        return evaluator
    return InjectingEvaluator(evaluator, spec=injection, benchmark_mode=benchmark_mode)


def assert_benchmark_only(benchmark_mode: bool) -> None:
    if not benchmark_mode:
        raise BenchmarkInjectionError(
            "benchmark fault injection is TEST/BENCHMARK ONLY"
        )


def write_fixture_workspace(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

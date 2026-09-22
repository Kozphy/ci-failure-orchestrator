"""Evaluator — turns SandboxResult into structured EvaluationResult."""

from __future__ import annotations

from typing import Protocol

from .models import (
    CheckStatus,
    EvaluationCheck,
    EvaluationResult,
    RepairProposal,
    SandboxResult,
    utc_now,
)

FORBIDDEN_MARKERS = (
    "secrets/",
    ".env",
    "id_rsa",
)


class EvaluationError(RuntimeError):
    pass


class Evaluator(Protocol):
    def evaluate(
        self,
        *,
        proposal: RepairProposal,
        sandbox: SandboxResult,
    ) -> EvaluationResult: ...


class LocalEvaluator:
    """Evidence-based local evaluator. Does not retry or approve remediation."""

    def evaluate(
        self,
        *,
        proposal: RepairProposal,
        sandbox: SandboxResult,
    ) -> EvaluationResult:
        if not proposal.run_id:
            raise EvaluationError("proposal.run_id required")

        checks: list[EvaluationCheck] = []
        evidence: list[str] = []

        patch_applied = sandbox.patch_applied and sandbox.error is None
        checks.append(
            EvaluationCheck(
                "PATCH_APPLIED",
                CheckStatus.PASSED if patch_applied else CheckStatus.FAILED,
                sandbox.error or "applied",
            )
        )
        evidence.append(f"patch_applied={patch_applied}")

        target = next((c for c in sandbox.command_results if c.tool_name == "test_runner"), None)
        if target is None:
            target_status = CheckStatus.NOT_RUN
            target_passed = False
            checks.append(EvaluationCheck("TARGET_TEST_PASSED", CheckStatus.NOT_RUN, "no_test_runner_result"))
        else:
            target_passed = target.success
            target_status = CheckStatus.PASSED if target.success else CheckStatus.FAILED
            checks.append(EvaluationCheck("TARGET_TEST_PASSED", target_status, target.stdout[:200]))
        evidence.append(f"target_verification={target_status.value}")

        # Relevant tests: unavailable unless explicitly present
        relevant = next(
            (c for c in sandbox.command_results if c.metadata.get("step") == "relevant_tests"),
            None,
        )
        if relevant is None:
            checks.append(EvaluationCheck("RELEVANT_TESTS_PASSED", CheckStatus.UNAVAILABLE, "not_configured"))
        else:
            checks.append(
                EvaluationCheck(
                    "RELEVANT_TESTS_PASSED",
                    CheckStatus.PASSED if relevant.success else CheckStatus.FAILED,
                    relevant.stdout[:200],
                )
            )

        forbidden = False
        for path in sandbox.changed_files or proposal.files_changed:
            normalized = path.replace("\\", "/").lower()
            if any(marker in normalized for marker in FORBIDDEN_MARKERS):
                forbidden = True
                break
        checks.append(
            EvaluationCheck(
                "NO_FORBIDDEN_FILES_CHANGED",
                CheckStatus.FAILED if forbidden else CheckStatus.PASSED,
                "forbidden_detected" if forbidden else "ok",
            )
        )
        evidence.append(f"forbidden_changes={forbidden}")

        # Lint/type: skip unless command results exist
        for name, key in (("NO_NEW_LINT_ERRORS", "lint"), ("NO_NEW_TYPE_ERRORS", "typecheck")):
            hit = next((c for c in sandbox.command_results if c.tool_name == key), None)
            if hit is None:
                checks.append(EvaluationCheck(name, CheckStatus.SKIPPED, "not_run"))
            else:
                checks.append(
                    EvaluationCheck(
                        name,
                        CheckStatus.PASSED if hit.success else CheckStatus.FAILED,
                        hit.stdout[:120],
                    )
                )

        regressions = bool(sandbox.timeout) or (target is not None and not target.success and patch_applied)
        # Prefer explicit: regressions if target failed after apply
        if target is not None and not target.success:
            regressions = True
        evidence.append(f"regressions_detected={regressions}")

        passed = (
            patch_applied
            and not forbidden
            and not sandbox.timeout
            and (target is None or target.success)
            and sandbox.error is None
        )
        # If target was NOT_RUN but patch applied and no forbidden — still fail closed on missing target when plan required it
        if target is None:
            passed = False
            evidence.append("fail_closed_missing_target_verification")

        return EvaluationResult(
            run_id=proposal.run_id,
            passed=passed,
            patch_applied=patch_applied,
            target_verification_passed=bool(target and target.success),
            regressions_detected=regressions,
            forbidden_changes_detected=forbidden,
            checks=tuple(checks),
            evidence=tuple(evidence),
            timestamp=utc_now(),
        )

"""Evaluation layer + EvalForge adapter boundary."""

from __future__ import annotations

from typing import Protocol

from .models import EvaluationResult, RepairProposal, SandboxResult, utc_now


class Evaluator(Protocol):
    def evaluate(
        self,
        *,
        run_id: str,
        proposal: RepairProposal,
        sandbox: SandboxResult,
        target_check_passed: bool,
    ) -> EvaluationResult:
        ...


class LocalEvaluator:
    """Structured local evaluation without a meaningless single quality score."""

    def evaluate(
        self,
        *,
        run_id: str,
        proposal: RepairProposal,
        sandbox: SandboxResult,
        target_check_passed: bool,
    ) -> EvaluationResult:
        evidence: list[str] = []
        applied = sandbox.applied and sandbox.error is None
        evidence.append(f"sandbox_applied={applied}")
        evidence.append(f"target_check_passed={target_check_passed}")

        forbidden = any(
            marker in path.replace("\\", "/").lower()
            for path in proposal.files_affected
            for marker in (".github/workflows/", "secret", "auth/")
        )
        policy_safe = not forbidden
        evidence.append(f"policy_safe={policy_safe}")

        regression_free = applied and not sandbox.timed_out
        evidence.append(f"regression_free={regression_free}")

        passed = applied and target_check_passed and policy_safe and regression_free
        return EvaluationResult(
            run_id=run_id,
            passed=passed,
            target_check_passed=target_check_passed,
            regression_free=regression_free,
            policy_safe=policy_safe,
            evidence=tuple(evidence),
            score=None,
            timestamp=utc_now(),
        )


class EvalForgeAdapter:
    """Reference adapter boundary for an external EvalForge evaluation system.

    Does not require EvalForge to be installed. Callers inject ``submit`` /
    ``fetch`` callables when integrating a real service.
    """

    def __init__(self, submit=None, fetch=None) -> None:
        self._submit = submit
        self._fetch = fetch

    def evaluate(
        self,
        *,
        run_id: str,
        proposal: RepairProposal,
        sandbox: SandboxResult,
        target_check_passed: bool,
    ) -> EvaluationResult:
        if self._submit is None or self._fetch is None:
            # Fall back to local structured evaluation when remote is unavailable.
            return LocalEvaluator().evaluate(
                run_id=run_id,
                proposal=proposal,
                sandbox=sandbox,
                target_check_passed=target_check_passed,
            )
        payload = {
            "run_id": run_id,
            "proposal_id": proposal.proposal_id,
            "files": list(proposal.files_affected),
            "sandbox_ok": sandbox.applied,
            "target_check_passed": target_check_passed,
        }
        handle = self._submit(payload)
        remote = self._fetch(handle)
        return EvaluationResult(
            run_id=run_id,
            passed=bool(remote.get("passed")),
            target_check_passed=bool(remote.get("target_check_passed", target_check_passed)),
            regression_free=bool(remote.get("regression_free", True)),
            policy_safe=bool(remote.get("policy_safe", True)),
            evidence=tuple(remote.get("evidence") or ("evalforge",)),
            score=remote.get("score"),
            timestamp=utc_now(),
        )

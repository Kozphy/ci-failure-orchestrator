"""Evaluation layer + EvalForge adapter boundary."""

from __future__ import annotations

import hashlib
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
    ) -> EvaluationResult: ...


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
    """Strict independent evaluation gate; local fallback requires explicit opt-in.

    Provider callables must enforce transport timeouts. This adapter never turns
    missing, malformed, contradictory or unavailable evaluation into approval.
    """

    def __init__(self, submit=None, fetch=None, *, allow_local_fallback: bool = False) -> None:
        self._submit = submit
        self._fetch = fetch
        self._allow_local_fallback = allow_local_fallback

    @staticmethod
    def _blocked(run_id: str, reason: str) -> EvaluationResult:
        return EvaluationResult(
            run_id=run_id,
            passed=False,
            target_check_passed=False,
            regression_free=False,
            policy_safe=False,
            evidence=(f"evalforge_blocked:{reason}",),
            timestamp=utc_now(),
        )

    def evaluate(
        self,
        *,
        run_id: str,
        proposal: RepairProposal,
        sandbox: SandboxResult,
        target_check_passed: bool,
    ) -> EvaluationResult:
        if proposal.run_id != run_id or sandbox.run_id != run_id or sandbox.proposal_id != proposal.proposal_id:
            return self._blocked(run_id, "local_identity_mismatch")
        if self._submit is None or self._fetch is None:
            if not self._allow_local_fallback:
                return self._blocked(run_id, "independent_evaluation_required")
            local = LocalEvaluator().evaluate(
                run_id=run_id,
                proposal=proposal,
                sandbox=sandbox,
                target_check_passed=target_check_passed,
            )
            from dataclasses import replace

            return replace(local, evidence=("local_fallback_not_independent", *local.evidence))
        proposal_sha256 = hashlib.sha256(proposal.proposed_patch.encode("utf-8")).hexdigest()
        payload = {
            "run_id": run_id,
            "proposal_id": proposal.proposal_id,
            "proposal_sha256": proposal_sha256,
            "files": list(proposal.files_affected),
            "sandbox_ok": sandbox.applied,
            "target_check_passed": target_check_passed,
        }
        try:
            handle = self._submit(payload)
            remote = self._fetch(handle)
        except Exception as exc:  # noqa: BLE001 - untrusted provider must fail closed
            # Record type only: provider exception text may contain credentials.
            return self._blocked(run_id, f"provider_error:{type(exc).__name__}")
        required = {
            "run_id",
            "proposal_id",
            "proposal_sha256",
            "passed",
            "target_check_passed",
            "regression_free",
            "policy_safe",
            "evidence",
        }
        if not isinstance(remote, dict) or not required.issubset(remote) or set(remote) - required - {"score"}:
            return self._blocked(run_id, "invalid_schema")
        if (
            remote["run_id"] != run_id
            or remote["proposal_id"] != proposal.proposal_id
            or remote["proposal_sha256"] != proposal_sha256
        ):
            return self._blocked(run_id, "remote_identity_mismatch")
        flags = ("passed", "target_check_passed", "regression_free", "policy_safe")
        if any(type(remote[k]) is not bool for k in flags):
            return self._blocked(run_id, "non_boolean_result")
        evidence = remote["evidence"]
        if (
            not isinstance(evidence, list)
            or not 1 <= len(evidence) <= 64
            or any(not isinstance(e, str) or not e.strip() or len(e) > 2048 for e in evidence)
        ):
            return self._blocked(run_id, "invalid_evidence")
        import math

        score = remote.get("score")
        if score is not None and (type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1):
            return self._blocked(run_id, "invalid_score")
        local_ok = (
            sandbox.applied is True and sandbox.error is None and not sandbox.timed_out and target_check_passed is True
        )
        if remote["passed"] and (not all(remote[k] for k in flags) or not local_ok):
            return self._blocked(run_id, "contradictory_pass")
        return EvaluationResult(
            run_id=run_id,
            passed=remote["passed"],
            target_check_passed=remote["target_check_passed"],
            regression_free=remote["regression_free"],
            policy_safe=remote["policy_safe"],
            evidence=("independent_evalforge_response", *evidence),
            score=score,
            timestamp=utc_now(),
        )

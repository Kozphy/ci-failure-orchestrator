"""Bounded retry decisions for the governed pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import EvaluationResult, RepairProposal, RetryDecision, utc_now


@dataclass
class RetryBudget:
    max_attempts: int = 3
    attempts_used: int = 0
    repeated_failure_limit: int = 2
    _failure_fingerprints: list[str] = field(default_factory=list)
    _patch_fingerprints: list[str] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.max_attempts - self.attempts_used)

    def record_attempt(
        self,
        *,
        failure_fingerprint: str,
        patch_fingerprint: str | None = None,
    ) -> None:
        self.attempts_used += 1
        self._failure_fingerprints.append(failure_fingerprint)
        if patch_fingerprint:
            self._patch_fingerprints.append(patch_fingerprint)

    def decide(
        self,
        *,
        run_id: str,
        evaluation: EvaluationResult | None,
        proposal: RepairProposal | None = None,
        unrecoverable: bool = False,
        policy_blocks_retry: bool = False,
        requires_human: bool = False,
    ) -> RetryDecision:
        if unrecoverable:
            return RetryDecision(run_id, False, self.attempts_used, self.max_attempts, "unrecoverable", utc_now())
        if requires_human:
            return RetryDecision(run_id, False, self.attempts_used, self.max_attempts, "human_required", utc_now())
        if policy_blocks_retry:
            return RetryDecision(run_id, False, self.attempts_used, self.max_attempts, "policy_blocks_retry", utc_now())
        if self.attempts_used >= self.max_attempts:
            return RetryDecision(run_id, False, self.attempts_used, self.max_attempts, "budget_exhausted", utc_now())

        if evaluation and evaluation.passed:
            return RetryDecision(run_id, False, self.attempts_used, self.max_attempts, "evaluation_passed", utc_now())

        if len(self._failure_fingerprints) >= self.repeated_failure_limit:
            recent = self._failure_fingerprints[-self.repeated_failure_limit :]
            if len(set(recent)) == 1:
                return RetryDecision(
                    run_id,
                    False,
                    self.attempts_used,
                    self.max_attempts,
                    "repeated_identical_failure",
                    utc_now(),
                )

        if proposal and len(self._patch_fingerprints) >= 2:
            if self._patch_fingerprints[-1] == self._patch_fingerprints[-2]:
                return RetryDecision(
                    run_id,
                    False,
                    self.attempts_used,
                    self.max_attempts,
                    "repeated_identical_patch",
                    utc_now(),
                )

        return RetryDecision(run_id, True, self.attempts_used, self.max_attempts, "retry_allowed", utc_now())

"""Phase 7 — bounded, deterministic retry budget for the foundation pipeline.

Attempt semantics:
  max_attempts=3 means attempt 1 (initial) + up to 2 retries.
Proposal/failure fingerprints are heuristic duplicate detectors, not security hashes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .models import EvaluationResult, FailureClassification, FailureEvent, RepairProposal, SandboxResult, utc_now


class RetryReason(str, Enum):
    # RETRY
    RECOVERABLE_FAILURE = "RECOVERABLE_FAILURE"
    PARTIAL_PROGRESS = "PARTIAL_PROGRESS"
    ALTERNATIVE_PLAN_AVAILABLE = "ALTERNATIVE_PLAN_AVAILABLE"
    TRANSIENT_TOOL_FAILURE = "TRANSIENT_TOOL_FAILURE"
    TRANSIENT_SANDBOX_FAILURE = "TRANSIENT_SANDBOX_FAILURE"
    # STOP
    SUCCESS = "SUCCESS"
    MAX_ATTEMPTS_EXHAUSTED = "MAX_ATTEMPTS_EXHAUSTED"
    IDENTICAL_PROPOSAL_REPEATED = "IDENTICAL_PROPOSAL_REPEATED"
    IDENTICAL_FAILURE_REPEATED = "IDENTICAL_FAILURE_REPEATED"
    NO_PROGRESS = "NO_PROGRESS"
    UNRECOVERABLE_FAILURE = "UNRECOVERABLE_FAILURE"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    SECURITY_BOUNDARY_HIT = "SECURITY_BOUNDARY_HIT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class FailureDisposition(str, Enum):
    RECOVERABLE = "RECOVERABLE"
    TRANSIENT = "TRANSIENT"
    UNRECOVERABLE = "UNRECOVERABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RetryBudget:
    """Finite retry configuration.

    ``max_attempts`` is the hard upper bound on total repair attempts
    (initial + retries). It must be >= 1.
    """

    max_attempts: int = 3
    max_identical_failures: int = 2
    max_identical_proposals: int = 1
    max_no_progress_attempts: int = 2
    max_retry_history_entries: int = 3

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1 (finite)")
        if self.max_identical_failures < 1:
            raise ValueError("max_identical_failures must be >= 1")
        if self.max_identical_proposals < 1:
            raise ValueError("max_identical_proposals must be >= 1")
        if self.max_no_progress_attempts < 1:
            raise ValueError("max_no_progress_attempts must be >= 1")
        if self.max_retry_history_entries < 1:
            raise ValueError("max_retry_history_entries must be >= 1")


@dataclass(frozen=True)
class ProgressAssessment:
    improved: bool
    signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class AttemptRecord:
    attempt_number: int
    plan_goal: str
    proposal_id: str
    proposal_fingerprint: str
    failure_fingerprint: str
    evaluation_passed: bool
    patch_applied: bool
    target_passed: bool
    failed_check_count: int
    sandbox_error: str | None
    disposition: FailureDisposition
    progress: ProgressAssessment | None = None
    started_at: str = field(default_factory=utc_now)
    completed_at: str = field(default_factory=utc_now)
    summary: str = ""


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    reason: RetryReason
    next_attempt: int
    budget_remaining: int
    progress_detected: bool
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetryContext:
    attempt_number: int
    prior_attempts: tuple[AttemptRecord, ...]
    failed_approaches: tuple[str, ...]
    latest_evaluation: EvaluationResult | None
    budget: RetryBudget


_TEMP_PATH = re.compile(r"(?i)(/tmp/|/var/folders/|[a-z]:\\users\\[^\\]+\\appdata\\local\\temp\\)[^\s]+")
_UUIDISH = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_RUN_ID = re.compile(r"\brun-[a-z0-9]+\b", re.I)
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")


def normalize_patch(patch: str) -> str:
    """Deterministic patch normalization for fingerprinting."""

    lines = []
    for line in (patch or "").replace("\r\n", "\n").split("\n"):
        stripped = line.rstrip()
        if stripped.startswith("+++ ") or stripped.startswith("--- "):
            # Drop volatile timestamps after tab if present
            stripped = stripped.split("\t", 1)[0]
        lines.append(stripped)
    # Collapse trailing blank lines
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def proposal_fingerprint(proposal: RepairProposal) -> str:
    payload = "\n".join(
        [
            normalize_patch(proposal.patch),
            "\n".join(sorted(p.replace("\\", "/") for p in proposal.files_changed)),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stabilize(text: str) -> str:
    text = _TEMP_PATH.sub("<TMP>", text)
    text = _UUIDISH.sub("<ID>", text)
    text = _RUN_ID.sub("<RUN>", text)
    text = _TS.sub("<TS>", text)
    return text


def failure_fingerprint(
    *,
    event: FailureEvent | None = None,
    classification: FailureClassification | None = None,
    evaluation: EvaluationResult | None = None,
    sandbox: SandboxResult | None = None,
) -> str:
    """Heuristic duplicate-failure fingerprint (not root-cause identity)."""

    parts: list[str] = []
    if classification is not None:
        parts.append(f"category={classification.category}")
    if event is not None:
        parts.append(f"step={event.failed_step}")
        parts.append(f"exit={event.exit_code}")
        msg = _stabilize(event.message or "")
        # Keep a short signature line
        first = next((ln.strip() for ln in msg.splitlines() if ln.strip()), "")
        parts.append(f"msg={first[:240]}")
        for hay in (event.message, event.log_excerpt):
            if "::" in (hay or "") or "test_" in (hay or ""):
                parts.append(f"test_hint={_stabilize(hay)[:160]}")
                break
    if evaluation is not None:
        failed = sorted(
            c.name for c in evaluation.checks if c.status.value == "FAILED"
        )
        parts.append("failed_checks=" + ",".join(failed))
        parts.append(f"target_pass={evaluation.target_verification_passed}")
        parts.append(f"forbidden={evaluation.forbidden_changes_detected}")
    if sandbox is not None and sandbox.error:
        parts.append(f"sandbox_error={_stabilize(sandbox.error)[:120]}")
    blob = "\n".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def assess_progress(
    previous: AttemptRecord | None,
    current: AttemptRecord,
) -> ProgressAssessment:
    if previous is None:
        return ProgressAssessment(improved=False, signals=("first_attempt",))

    signals: list[str] = []
    if (not previous.target_passed) and current.target_passed:
        signals.append("target_test_now_passes")
    if current.failed_check_count < previous.failed_check_count:
        signals.append("remaining_failure_count_decreased")
    if (not previous.patch_applied) and current.patch_applied:
        signals.append("patch_now_applies")
    if previous.sandbox_error and not current.sandbox_error:
        signals.append("sandbox_reached_further")
    if (
        previous.failure_fingerprint != current.failure_fingerprint
        and current.failed_check_count <= previous.failed_check_count
        and current.patch_applied
    ):
        # Different fingerprint alone is not progress; only when objective counts improve/hold with apply
        if current.failed_check_count < previous.failed_check_count or current.target_passed:
            signals.append("failure_signature_improved")

    # Different error with no objective improvement ≠ progress
    return ProgressAssessment(improved=bool(signals), signals=tuple(signals))


def classify_disposition(
    *,
    evaluation: EvaluationResult,
    sandbox: SandboxResult,
) -> FailureDisposition:
    err = (sandbox.error or "").lower()
    if evaluation.forbidden_changes_detected or "forbidden_path" in err:
        return FailureDisposition.UNRECOVERABLE
    if err in {"empty_patch", "binary_patch_rejected"} or "invalid" in err:
        return FailureDisposition.UNRECOVERABLE
    if sandbox.timeout or "timeout" in err or "setup" in err:
        return FailureDisposition.TRANSIENT
    if evaluation.passed:
        return FailureDisposition.RECOVERABLE
    if not evaluation.patch_applied and sandbox.error:
        if "sandbox_setup_error" in err:
            return FailureDisposition.TRANSIENT
    if evaluation.patch_applied and not evaluation.passed:
        return FailureDisposition.RECOVERABLE
    return FailureDisposition.UNKNOWN


def build_attempt_record(
    *,
    attempt_number: int,
    plan_goal: str,
    proposal: RepairProposal,
    evaluation: EvaluationResult,
    sandbox: SandboxResult,
    event: FailureEvent,
    classification: FailureClassification,
    previous: AttemptRecord | None = None,
) -> AttemptRecord:
    prop_fp = proposal_fingerprint(proposal)
    fail_fp = failure_fingerprint(
        event=event,
        classification=classification,
        evaluation=evaluation,
        sandbox=sandbox,
    )
    failed_checks = sum(1 for c in evaluation.checks if c.status.value == "FAILED")
    disposition = classify_disposition(evaluation=evaluation, sandbox=sandbox)
    record = AttemptRecord(
        attempt_number=attempt_number,
        plan_goal=plan_goal,
        proposal_id=proposal.proposal_id,
        proposal_fingerprint=prop_fp,
        failure_fingerprint=fail_fp,
        evaluation_passed=evaluation.passed,
        patch_applied=evaluation.patch_applied,
        target_passed=evaluation.target_verification_passed,
        failed_check_count=failed_checks,
        sandbox_error=sandbox.error,
        disposition=disposition,
        completed_at=utc_now(),
        summary=(
            f"attempt={attempt_number} passed={evaluation.passed} "
            f"failed_checks={failed_checks} disposition={disposition.value}"
        ),
    )
    progress = assess_progress(previous, record)
    return AttemptRecord(
        **{
            **record.__dict__,
            "progress": progress,
        }
    )


class RetryDecisionEngine:
    """Deterministic retry control plane — does not generate repairs."""

    def decide(
        self,
        budget: RetryBudget,
        attempts: list[AttemptRecord],
        latest_evaluation: EvaluationResult,
    ) -> RetryDecision:
        if not attempts:
            return RetryDecision(
                should_retry=False,
                reason=RetryReason.INSUFFICIENT_EVIDENCE,
                next_attempt=1,
                budget_remaining=budget.max_attempts,
                progress_detected=False,
                evidence=("no_attempts_recorded",),
            )

        latest = attempts[-1]
        used = len(attempts)
        remaining = max(0, budget.max_attempts - used)
        progress = bool(latest.progress and latest.progress.improved)

        # 1. Success
        if latest_evaluation.passed or latest.evaluation_passed:
            return RetryDecision(
                False,
                RetryReason.SUCCESS,
                used,
                remaining,
                progress,
                ("evaluation_passed",),
            )

        # 2. Max attempts
        if used >= budget.max_attempts:
            return RetryDecision(
                False,
                RetryReason.MAX_ATTEMPTS_EXHAUSTED,
                used,
                0,
                progress,
                (f"attempts={used}", f"max={budget.max_attempts}"),
            )

        # 3. Unrecoverable / security / invalid
        if latest.disposition is FailureDisposition.UNRECOVERABLE:
            reason = RetryReason.UNRECOVERABLE_FAILURE
            if latest_evaluation.forbidden_changes_detected or (
                latest.sandbox_error and "forbidden" in latest.sandbox_error
            ):
                reason = RetryReason.SECURITY_BOUNDARY_HIT
            if latest.sandbox_error in {"empty_patch", "binary_patch_rejected"}:
                reason = RetryReason.INVALID_PROPOSAL
            return RetryDecision(
                False,
                reason,
                used,
                remaining,
                progress,
                (f"disposition={latest.disposition.value}", latest.sandbox_error or ""),
            )

        # 4. Identical proposal threshold
        # max_identical_proposals=1 means stop when a second identical appears
        prop_counts: dict[str, int] = {}
        for a in attempts:
            prop_counts[a.proposal_fingerprint] = prop_counts.get(a.proposal_fingerprint, 0) + 1
        if prop_counts.get(latest.proposal_fingerprint, 0) > budget.max_identical_proposals:
            return RetryDecision(
                False,
                RetryReason.IDENTICAL_PROPOSAL_REPEATED,
                used,
                remaining,
                progress,
                (
                    f"fingerprint={latest.proposal_fingerprint[:12]}",
                    f"count={prop_counts[latest.proposal_fingerprint]}",
                ),
            )

        # 5. Identical failure without progress
        fail_counts: dict[str, int] = {}
        for a in attempts:
            fail_counts[a.failure_fingerprint] = fail_counts.get(a.failure_fingerprint, 0) + 1
        identical_fail_count = fail_counts.get(latest.failure_fingerprint, 0)
        if identical_fail_count >= budget.max_identical_failures and not progress:
            return RetryDecision(
                False,
                RetryReason.IDENTICAL_FAILURE_REPEATED,
                used,
                remaining,
                False,
                (
                    f"failure_fp={latest.failure_fingerprint[:12]}",
                    f"count={identical_fail_count}",
                ),
            )

        # 6. No-progress streak (consecutive trailing attempts without improvement)
        streak = 0
        for a in reversed(attempts):
            if a.progress and a.progress.improved:
                break
            streak += 1
        if streak >= budget.max_no_progress_attempts:
            return RetryDecision(
                False,
                RetryReason.NO_PROGRESS,
                used,
                remaining,
                False,
                (f"no_progress_streak={streak}",),
            )

        # 7. Recoverable / transient / partial progress
        if progress:
            return RetryDecision(
                True,
                RetryReason.PARTIAL_PROGRESS,
                used + 1,
                remaining - 1,
                True,
                tuple(latest.progress.signals) if latest.progress else (),
            )
        if latest.disposition is FailureDisposition.TRANSIENT:
            return RetryDecision(
                True,
                RetryReason.TRANSIENT_SANDBOX_FAILURE
                if latest.sandbox_error
                else RetryReason.TRANSIENT_TOOL_FAILURE,
                used + 1,
                remaining - 1,
                False,
                (f"disposition={latest.disposition.value}",),
            )
        if latest.disposition is FailureDisposition.RECOVERABLE:
            # Prefer alternative plan when prior proposal fingerprints exist
            reason = RetryReason.RECOVERABLE_FAILURE
            if used >= 1:
                reason = RetryReason.ALTERNATIVE_PLAN_AVAILABLE
            return RetryDecision(
                True,
                reason,
                used + 1,
                remaining - 1,
                False,
                (f"disposition={latest.disposition.value}",),
            )

        # 8. Unknown → conservative stop
        return RetryDecision(
            False,
            RetryReason.INSUFFICIENT_EVIDENCE,
            used,
            remaining,
            progress,
            ("disposition=UNKNOWN", "conservative_stop"),
        )


def retry_history_summaries(
    attempts: list[AttemptRecord],
    *,
    limit: int = 3,
) -> tuple[dict[str, Any], ...]:
    """Compact retry history for context builder (bounded)."""

    selected = attempts[-limit:]
    out: list[dict[str, Any]] = []
    for a in selected:
        out.append(
            {
                "summary": (
                    f"Attempt {a.attempt_number}: approach={a.plan_goal[:80]}; "
                    f"result={'PASS' if a.evaluation_passed else 'FAIL'}; "
                    f"target_passed={a.target_passed}; "
                    f"failed_checks={a.failed_check_count}; "
                    f"proposal_fp={a.proposal_fingerprint[:12]}; "
                    f"failure_fp={a.failure_fingerprint[:12]}; "
                    f"progress={bool(a.progress and a.progress.improved)}"
                )
            }
        )
    return tuple(out)

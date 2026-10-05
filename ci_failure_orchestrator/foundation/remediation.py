"""The single deterministic decision on whether a repair is genuinely verified.

A green pipeline is necessary evidence, but it is not sufficient evidence of a correct
repair. ``decide_remediation`` turns the collected evidence into one final state and
``is_verified_fix`` is the only path to ``VERIFIED_FIXED``. No model output is an input.

Evidence that was not collected is ``None`` (or ``GateStatus.NOT_RUN``) and never counts as
a pass. Missing evidence can at best produce ``CI_GREEN_BUT_UNVERIFIED``.

These states describe the repair. They sit beside the foundation's workflow states
(``RunStatus``), which are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any

from .diff_risk import HIGH, LOW, MEDIUM


class RemediationState(str, Enum):
    """Repair states, from failure received to a terminal verification verdict."""

    FAILURE_RECEIVED = "FAILURE_RECEIVED"
    FAILURE_REPRODUCED = "FAILURE_REPRODUCED"
    REPAIR_PROPOSED = "REPAIR_PROPOSED"
    PATCH_APPLIED = "PATCH_APPLIED"
    TARGETED_VALIDATION_PASSED = "TARGETED_VALIDATION_PASSED"
    REGRESSION_VALIDATION_PASSED = "REGRESSION_VALIDATION_PASSED"
    POLICY_APPROVED = "POLICY_APPROVED"
    CI_GREEN_BUT_UNVERIFIED = "CI_GREEN_BUT_UNVERIFIED"
    VERIFIED_FIXED = "VERIFIED_FIXED"
    REGRESSION_DETECTED = "REGRESSION_DETECTED"
    POLICY_REJECTED = "POLICY_REJECTED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    # The patch did not make the original failure go away (or replaced it with another one).
    NOT_FIXED = "NOT_FIXED"


TERMINAL_STATES = frozenset({
    RemediationState.CI_GREEN_BUT_UNVERIFIED,
    RemediationState.VERIFIED_FIXED,
    RemediationState.REGRESSION_DETECTED,
    RemediationState.POLICY_REJECTED,
    RemediationState.HUMAN_REVIEW_REQUIRED,
    RemediationState.NOT_FIXED,
})


class GateStatus(str, Enum):
    """Outcomes of one verification gate."""

    PASSED = "PASSED"
    # Passed before the patch and fails after it: the repair broke it.
    FAILED = "FAILED"
    # Failed before the patch too: not caused by the repair, but it cannot vouch for it either.
    FAILED_PREEXISTING = "FAILED_PREEXISTING"
    NOT_RUN = "NOT_RUN"
    # Explicitly waived in the verification config, with a recorded reason.
    WAIVED = "WAIVED"

    @property
    def satisfied(self) -> bool:
        """Whether the gate passed or was waived."""
        return self in (GateStatus.PASSED, GateStatus.WAIVED)

    @property
    def passed(self) -> bool | None:
        """True if the gate is satisfied, None if it was not run, otherwise False."""

        if self.satisfied:
            return True
        if self is GateStatus.NOT_RUN:
            return None
        return False


class MergeRequirement(str, Enum):
    """What must happen before merge. This tool never merges; it only reports the requirement."""

    AUTOMATIC_VERIFICATION_ALLOWED = "AUTOMATIC_VERIFICATION_ALLOWED"
    HUMAN_APPROVAL_BEFORE_MERGE = "HUMAN_APPROVAL_BEFORE_MERGE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


QUALITY_GATES = ("lint", "typecheck", "security", "build")
_GATES = ("affected_tests", "regression_suite", "coverage", *QUALITY_GATES, "behavioral_invariants")


@dataclass(frozen=True)
class VerificationResult:
    """Evidence about one repair. Defaults are the fail-safe "nothing was shown" values."""

    repair_proposed: bool = False
    patch_applied: bool = False
    original_failure_reproduced: bool | None = None
    original_failure_resolved: bool | None = None
    targeted_test_passed: bool | None = None
    # The originally failing test can no longer be found after the patch (deleted or renamed).
    target_test_missing: bool = False
    affected_tests: GateStatus = GateStatus.NOT_RUN
    regression_suite: GateStatus = GateStatus.NOT_RUN
    new_test_failures: tuple[str, ...] = ()
    test_count_decreased: bool | None = None
    skipped_tests_increased: bool | None = None
    coverage: GateStatus = GateStatus.NOT_RUN
    lint: GateStatus = GateStatus.NOT_RUN
    typecheck: GateStatus = GateStatus.NOT_RUN
    security: GateStatus = GateStatus.NOT_RUN
    build: GateStatus = GateStatus.NOT_RUN
    behavioral_invariants: GateStatus = GateStatus.NOT_RUN
    forbidden_diff_detected: bool = False
    forbidden_diff_codes: tuple[str, ...] = ()
    policy_outcome: str | None = None
    human_approved: bool = False
    real_ci_passed: bool | None = None
    risk_level: str = HIGH
    risk_reasons: tuple[str, ...] = ()

    @property
    def affected_tests_passed(self) -> bool | None:
        """Pass state of the affected-tests gate; None if not run."""
        return self.affected_tests.passed

    @property
    def regression_suite_passed(self) -> bool | None:
        """Pass state of the regression-suite gate; None if not run."""
        return self.regression_suite.passed

    @property
    def coverage_regressed(self) -> bool | None:
        """True if the coverage gate failed, False if it is satisfied, otherwise None."""

        if self.coverage is GateStatus.FAILED:
            return True
        return False if self.coverage.satisfied else None

    @property
    def lint_passed(self) -> bool | None:
        """Pass state of the lint gate; None if not run."""
        return self.lint.passed

    @property
    def typecheck_passed(self) -> bool | None:
        """Pass state of the typecheck gate; None if not run."""
        return self.typecheck.passed

    @property
    def security_checks_passed(self) -> bool | None:
        """Pass state of the security gate; None if not run."""
        return self.security.passed

    @property
    def build_passed(self) -> bool | None:
        """Pass state of the build gate; None if not run."""
        return self.build.passed

    @property
    def behavioral_invariants_passed(self) -> bool | None:
        """Pass state of the behavioral-invariants gate; None if not run."""
        return self.behavioral_invariants.passed

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerificationResult:
        """Build a result from a dict, ignoring unknown keys and coercing gate and tuple fields."""

        values: dict[str, Any] = {}
        defaults = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            raw = data[f.name]
            default = getattr(defaults, f.name)
            if isinstance(default, GateStatus):
                values[f.name] = GateStatus(raw)
            elif isinstance(default, tuple):
                values[f.name] = tuple(raw or ())
            else:
                values[f.name] = raw
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        """Return the result as a JSON-compatible dict, including the derived pass properties."""

        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            out[f.name] = value.value if isinstance(value, Enum) else list(value) if isinstance(value, tuple) else value
        for name in (
            "affected_tests_passed", "regression_suite_passed", "coverage_regressed", "lint_passed",
            "typecheck_passed", "security_checks_passed", "build_passed", "behavioral_invariants_passed",
        ):
            out[name] = getattr(self, name)
        return out


@dataclass(frozen=True)
class RemediationDecision:
    """Final remediation state with its reasons, missing evidence and merge requirement."""

    state: RemediationState
    reasons: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    merge_requirement: MergeRequirement
    trail: tuple[RemediationState, ...] = field(default=())

    @property
    def verified(self) -> bool:
        """Whether the state is VERIFIED_FIXED."""
        return self.state is RemediationState.VERIFIED_FIXED

    def to_dict(self) -> dict[str, Any]:
        """Return the decision as a JSON-compatible dict."""

        return {
            "state": self.state.value,
            "verified": self.verified,
            "reasons": list(self.reasons),
            "missing_evidence": list(self.missing_evidence),
            "merge_requirement": self.merge_requirement.value,
            "trail": [s.value for s in self.trail],
        }


def _policy_satisfied(v: VerificationResult) -> bool:
    return v.policy_outcome == "APPROVE" or v.human_approved


def _risk_satisfied(v: VerificationResult) -> bool:
    return v.risk_level in (LOW, MEDIUM) or v.human_approved


def is_verified_fix(v: VerificationResult) -> bool:
    """True only when every required piece of evidence is present and passing."""
    return all((
        v.repair_proposed,
        v.patch_applied,
        v.original_failure_reproduced is True,
        v.original_failure_resolved is True,
        v.targeted_test_passed is True,
        not v.target_test_missing,
        v.affected_tests.satisfied,
        v.regression_suite.satisfied,
        not v.new_test_failures,
        v.test_count_decreased is False,
        v.skipped_tests_increased is not True,
        v.coverage.satisfied,
        v.lint.satisfied,
        v.typecheck.satisfied,
        v.security.satisfied,
        v.build.satisfied,
        v.behavioral_invariants.satisfied,
        not v.forbidden_diff_detected,
        _policy_satisfied(v),
        _risk_satisfied(v),
        v.real_ci_passed is True,
    ))


def missing_evidence(v: VerificationResult) -> tuple[str, ...]:
    """Return the evidence items that were not collected or cannot vouch for the repair."""

    missing: list[str] = []
    if v.original_failure_reproduced is not True:
        missing.append("original_failure_reproduced")
    if v.original_failure_resolved is None:
        missing.append("original_failure_resolved")
    if v.targeted_test_passed is None:
        missing.append("targeted_test_passed")
    if v.test_count_decreased is None:
        missing.append("test_count_comparison")
    for gate in _GATES:
        status: GateStatus = getattr(v, gate)
        if status in (GateStatus.NOT_RUN, GateStatus.FAILED_PREEXISTING):
            missing.append(f"{gate}:{status.value}")
    if v.real_ci_passed is None:
        missing.append("real_ci_passed")
    return tuple(missing)


def _trail(v: VerificationResult, final: RemediationState) -> tuple[RemediationState, ...]:
    trail = [RemediationState.FAILURE_RECEIVED]
    if v.original_failure_reproduced:
        trail.append(RemediationState.FAILURE_REPRODUCED)
    if v.repair_proposed:
        trail.append(RemediationState.REPAIR_PROPOSED)
    if v.patch_applied:
        trail.append(RemediationState.PATCH_APPLIED)
    if v.targeted_test_passed and v.original_failure_resolved:
        trail.append(RemediationState.TARGETED_VALIDATION_PASSED)
        if v.regression_suite.satisfied and v.affected_tests.satisfied and not v.new_test_failures:
            trail.append(RemediationState.REGRESSION_VALIDATION_PASSED)
    if _policy_satisfied(v) and not v.forbidden_diff_detected:
        trail.append(RemediationState.POLICY_APPROVED)
    if trail[-1] is not final:
        trail.append(final)
    return tuple(trail)


def _merge_requirement_for_risk(v: VerificationResult) -> MergeRequirement:
    if v.risk_level == LOW and not v.human_approved:
        return MergeRequirement.AUTOMATIC_VERIFICATION_ALLOWED
    return MergeRequirement.HUMAN_APPROVAL_BEFORE_MERGE


def decide_remediation(v: VerificationResult) -> RemediationDecision:
    """Precedence: cheating, not fixed, regression, human review, then how much evidence exists."""

    missing = missing_evidence(v)

    def decide(state: RemediationState, reasons: list[str], merge: MergeRequirement) -> RemediationDecision:
        return RemediationDecision(state, tuple(reasons), missing, merge, _trail(v, state))

    rejected = [f"forbidden_diff:{code}" for code in v.forbidden_diff_codes]
    if v.forbidden_diff_detected and not rejected:
        rejected.append("forbidden_diff")
    if v.target_test_missing:
        rejected.append("target_test_missing_after_patch")
    if v.test_count_decreased:
        rejected.append("test_count_decreased")
    if v.skipped_tests_increased:
        rejected.append("skipped_tests_increased")
    if v.policy_outcome == "REJECT":
        rejected.append("policy_rejected")
    if rejected:
        return decide(RemediationState.POLICY_REJECTED, rejected, MergeRequirement.BLOCKED)

    not_fixed: list[str] = []
    if not v.repair_proposed or not v.patch_applied:
        not_fixed.append("no_applied_repair")
    if v.targeted_test_passed is False:
        not_fixed.append("targeted_validation_failed")
    if v.original_failure_resolved is False:
        not_fixed.append("original_failure_not_resolved")
    if not_fixed:
        return decide(RemediationState.NOT_FIXED, not_fixed, MergeRequirement.BLOCKED)

    regressions = [f"new_test_failure:{t}" for t in v.new_test_failures]
    regressions += [f"{gate}_regressed" for gate in _GATES if getattr(v, gate) is GateStatus.FAILED]
    if regressions:
        return decide(RemediationState.REGRESSION_DETECTED, regressions, MergeRequirement.BLOCKED)

    review: list[str] = []
    if not _risk_satisfied(v):
        review.append(f"risk_{v.risk_level.lower()}")
        review.extend(v.risk_reasons)
    if not _policy_satisfied(v):
        review.append(f"policy_{(v.policy_outcome or 'missing').lower()}")
    if v.real_ci_passed is False:
        review.append("real_ci_failed_after_local_verification")
    if review:
        return decide(RemediationState.HUMAN_REVIEW_REQUIRED, review, MergeRequirement.HUMAN_REVIEW_REQUIRED)

    if v.real_ci_passed is None:
        return decide(RemediationState.POLICY_APPROVED, ["awaiting_real_ci_verification"], _merge_requirement_for_risk(v))
    if not is_verified_fix(v):
        return decide(
            RemediationState.CI_GREEN_BUT_UNVERIFIED,
            ["real_ci_passed_but_evidence_incomplete"],
            MergeRequirement.HUMAN_REVIEW_REQUIRED,
        )
    return decide(RemediationState.VERIFIED_FIXED, ["all_verification_evidence_passed"], _merge_requirement_for_risk(v))

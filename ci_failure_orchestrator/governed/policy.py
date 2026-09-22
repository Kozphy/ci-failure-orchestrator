"""Declarative policy gate for repair proposals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import (
    EvaluationResult,
    FailureClassification,
    PolicyDecision,
    PolicyOutcome,
    RepairProposal,
    utc_now,
)


SENSITIVE_PATH_MARKERS = (
    ".github/workflows/",
    "auth",
    "secret",
    "permission",
    "deploy",
    "migration",
    "lock",
    "pyproject.toml",
)


@dataclass(frozen=True)
class PolicyConfig:
    escalate_on_sensitive_paths: bool = True
    reject_if_evaluation_failed: bool = True
    max_files_changed: int = 20
    allowed_failure_classes_for_auto: tuple[str, ...] = (
        "lint_failure",
        "type_failure",
        "test_failure",
        "lint",
        "formatting",
        "typing",
        "unit_test_failure",
        "TEST_ASSERTION",
        "TYPE_ERROR",
        "LINT_ERROR",
    )
    always_escalate_classes: tuple[str, ...] = (
        "unknown",
        "UNKNOWN",
        "infrastructure_failure",
        "network_failure",
        "NETWORK_ERROR",
        "flaky_failure",
        "dependency_failure",
        "configuration_failure",
        "SECURITY_ERROR",
    )


class PolicyEngine:
    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def evaluate(
        self,
        *,
        run_id: str,
        proposal: RepairProposal,
        classification: FailureClassification,
        evaluation: EvaluationResult,
        tool_names: tuple[str, ...] = (),
    ) -> PolicyDecision:
        reasons: list[str] = []

        if self.config.reject_if_evaluation_failed and not evaluation.passed:
            return PolicyDecision(run_id, PolicyOutcome.RETRY, ("evaluation_failed",), utc_now())

        if len(proposal.files_affected) > self.config.max_files_changed:
            return PolicyDecision(
                run_id,
                PolicyOutcome.REJECT,
                (f"too_many_files:{len(proposal.files_affected)}",),
                utc_now(),
            )

        if self.config.escalate_on_sensitive_paths:
            for path in proposal.files_affected:
                normalized = path.replace("\\", "/").lower()
                if any(marker in normalized for marker in SENSITIVE_PATH_MARKERS):
                    reasons.append(f"sensitive_path:{path}")
            if reasons:
                return PolicyDecision(run_id, PolicyOutcome.ESCALATE, tuple(reasons), utc_now())

        if classification.failure_class in self.config.always_escalate_classes:
            return PolicyDecision(
                run_id,
                PolicyOutcome.ESCALATE,
                (f"class_requires_escalation:{classification.failure_class}",),
                utc_now(),
            )

        if classification.failure_class not in self.config.allowed_failure_classes_for_auto:
            if classification.confidence < 0.6:
                return PolicyDecision(
                    run_id,
                    PolicyOutcome.ESCALATE,
                    (f"class_not_auto_eligible:{classification.failure_class}",),
                    utc_now(),
                )
            return PolicyDecision(
                run_id,
                PolicyOutcome.ESCALATE,
                (f"class_not_auto_eligible:{classification.failure_class}",),
                utc_now(),
            )

        if "test_runner" in tool_names and not evaluation.target_check_passed:
            return PolicyDecision(run_id, PolicyOutcome.RETRY, ("target_check_failed",), utc_now())

        if not evaluation.policy_safe:
            return PolicyDecision(run_id, PolicyOutcome.ESCALATE, ("evaluation_policy_unsafe",), utc_now())

        return PolicyDecision(run_id, PolicyOutcome.APPROVE, ("policy_pass",), utc_now())


def load_policy_hints_from_yaml(path: str | Path) -> dict:
    """Optional bridge to existing trust policy YAML (JSON-compatible)."""

    try:
        import yaml
    except ImportError:  # pragma: no cover
        return {}
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    return data if isinstance(data, dict) else {}

"""Failure classification adapter over existing taxonomies."""

from __future__ import annotations

from ..classifier import classify_error
from ..github_repair_adapter import FailedCheck, classify_failed_check
from .models import FailureClassification, FailureEvent, utc_now


# Map legacy taxonomies into a stable governed vocabulary where possible.
_LEGACY_TO_GOVERNED = {
    "TYPE_ERROR": "type_failure",
    "BUILD_ERROR": "build_failure",
    "NETWORK_ERROR": "network_failure",
    "DEPENDENCY_ERROR": "dependency_failure",
    "TEST_ASSERTION": "test_failure",
    "FLAKY_TEST": "flaky_failure",
    "PACKAGE_ERROR": "dependency_failure",
    "DEPLOYMENT_ERROR": "infrastructure_failure",
    "SECURITY_ERROR": "configuration_failure",
    "RUNTIME_ERROR": "infrastructure_failure",
    "UNKNOWN": "unknown",
    "lint": "lint_failure",
    "formatting": "lint_failure",
    "typing": "type_failure",
    "workflow_syntax": "configuration_failure",
    "unit_test_failure": "test_failure",
    "unknown": "unknown",
}


class FailureClassifier:
    """Heuristic classifier. Confidence is **not** calibrated."""

    def classify(self, event: FailureEvent) -> FailureClassification:
        message_class, message_conf = classify_error(event.message or event.log_excerpt)
        check = FailedCheck(
            workflow=event.workflow,
            job=event.job,
            failed_step=event.failed_step,
            log_excerpt=event.log_excerpt or event.message,
            changed_paths=event.changed_paths,
        )
        adapter_class = classify_failed_check(check)

        governed = _LEGACY_TO_GOVERNED.get(adapter_class) or _LEGACY_TO_GOVERNED.get(message_class, "unknown")
        # Prefer Actions-oriented class when not unknown; else message taxonomy.
        # Explicit flaky signals in the message override a generic test label.
        if message_class == "FLAKY_TEST":
            governed = "flaky_failure"
            confidence = max(message_conf, 0.85)
            evidence = (f"message_taxonomy={message_class}", f"actions_class={adapter_class}")
        elif adapter_class == "unknown":
            governed = _LEGACY_TO_GOVERNED.get(message_class, "unknown")
            confidence = message_conf
            evidence = (f"message_taxonomy={message_class}",)
        else:
            confidence = max(message_conf, 0.7)
            evidence = (f"actions_class={adapter_class}", f"message_taxonomy={message_class}")

        uncertainty = (
            "heuristic_regex_match_only"
            if governed != "unknown"
            else "no_strong_pattern_match"
        )
        next_action = {
            "lint_failure": "plan_format_or_lint_fix",
            "type_failure": "plan_type_annotation_fix",
            "test_failure": "plan_minimal_test_fix",
            "flaky_failure": "escalate_or_quarantine",
            "dependency_failure": "inspect_lockfiles_with_approval",
            "network_failure": "escalate_infrastructure",
            "infrastructure_failure": "escalate_infrastructure",
            "build_failure": "plan_build_fix",
            "configuration_failure": "escalate_config_review",
            "unknown": "escalate_human",
        }.get(governed, "escalate_human")

        return FailureClassification(
            run_id=event.run_id,
            failure_class=governed,
            confidence=float(confidence),
            evidence=evidence,
            uncertainty=uncertainty,
            recommended_next_action=next_action,
            calibrated=False,
            timestamp=utc_now(),
        )

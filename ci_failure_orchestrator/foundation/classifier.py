"""Heuristic failure classifier for the foundation pipeline."""

from __future__ import annotations

from ..classifier import classify_error
from ..github_repair_adapter import FailedCheck, classify_failed_check
from .models import FailureClassification, FailureEvent, utc_now

_MAP = {
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
    def classify(self, event: FailureEvent) -> FailureClassification:
        msg_class, msg_conf = classify_error(event.message or event.log_excerpt)
        adapter = classify_failed_check(
            FailedCheck(
                workflow=event.workflow,
                job=event.job,
                failed_step=event.failed_step,
                log_excerpt=event.log_excerpt or event.message,
                changed_paths=event.changed_paths,
            )
        )
        if msg_class == "FLAKY_TEST":
            category = "flaky_failure"
            confidence = max(msg_conf, 0.85)
            evidence = (f"message={msg_class}", f"actions={adapter}")
        elif adapter != "unknown":
            category = _MAP.get(adapter, "unknown")
            confidence = max(msg_conf, 0.7)
            evidence = (f"actions={adapter}", f"message={msg_class}")
        else:
            category = _MAP.get(msg_class, "unknown")
            confidence = msg_conf
            evidence = (f"message={msg_class}",)

        uncertainty = (
            "heuristic_regex_only" if category != "unknown" else "no_strong_pattern"
        )
        return FailureClassification(
            run_id=event.run_id,
            category=category,
            evidence=evidence,
            confidence=float(confidence),
            uncertainty=uncertainty,
            recommended_next_action=(
                "escalate_unknown" if category == "unknown" else "plan_minimal_repair"
            ),
            calibrated=False,
            timestamp=utc_now(),
        )

"""Heuristic failure classifier for the foundation pipeline."""

from __future__ import annotations

import re

from ..classifier import classify_error
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
    "SECURITY_ERROR": "security_scan_failure",
    "RUNTIME_ERROR": "infrastructure_failure",
    "TIMEOUT": "timeout_failure",
    "CONFIG_ERROR": "configuration_failure",
    "ENVIRONMENT_MISMATCH": "environment_failure",
    "UNKNOWN": "unknown",
    "lint": "lint_failure",
    "formatting": "lint_failure",
    "typing": "type_failure",
    "workflow_syntax": "configuration_failure",
    "unit_test_failure": "test_failure",
    "unknown": "unknown",
}

# Content-based environment signals outrank job/step names: a "test" job that fails on a
# missing package is a dependency failure, not a test failure. A timeout inside a test step
# may be a hang or a slow runner, so it is not a test failure either.
ENVIRONMENT_CLASSES = frozenset(
    {"DEPENDENCY_ERROR", "NETWORK_ERROR", "PACKAGE_ERROR", "DEPLOYMENT_ERROR", "TIMEOUT", "ENVIRONMENT_MISMATCH"}
)

# Consulted only when the shared table (``..classifier``, also used by experimental modules)
# matches nothing, so its existing classes keep their meaning.
_FALLBACK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ENVIRONMENT_MISMATCH",
        re.compile(
            r"requires a different python|the engine \"node\" is incompatible|code ebadengine"
            r"|has been compiled by a more recent version of the java runtime|unsupported major\.minor version",
            re.IGNORECASE,
        ),
    ),
    (
        "NETWORK_ERROR",
        re.compile(
            r"name or service not known|temporary failure in name resolution|could not resolve host|getaddrinfo"
            r"|failed to establish a new connection|network is unreachable",
            re.IGNORECASE,
        ),
    ),
    (
        "DEPENDENCY_ERROR",
        re.compile(
            r"cannot import name '[^']+' from '[^']+'|conflicting dependencies|resolutionimpossible"
            r"|no matching distribution found|could not find a version that satisfies",
            re.IGNORECASE,
        ),
    ),
    (
        "TIMEOUT",
        re.compile(
            r"exceeded the maximum execution time|has timed out|timeouterror|timeout expired|deadline exceeded",
            re.IGNORECASE,
        ),
    ),
    (
        "CONFIG_ERROR",
        re.compile(
            r"configerror|configurationerror|invalid config(?:uration)?\b|configuration error"
            r"|unknown (?:setting|config(?:uration)? key)|missing required (?:setting|config|environment variable)",
            re.IGNORECASE,
        ),
    ),
)
_TIMED_OUT_RE = re.compile(r"(?i)timed out")
_EXPLICITLY_FLAKY_RE = re.compile(r"(?i)flaky|intermittent")
# pytest -v result lines; a ``[2-5]`` suffix is pytest-repeat's repetition index, not a parameter.
_TEST_RESULT_RE = re.compile(r"^(\S+::[^\s\[]+)(\[\d+-\d+\])? (PASSED|FAILED)\b", re.MULTILINE)


def intermittent_tests(text: str) -> tuple[str, ...]:
    """Tests a log reports as both passed and failed: one run that repeated them got both results."""
    outcomes: dict[str, set[str]] = {}
    for test, _repeat, result in _TEST_RESULT_RE.findall(text):
        outcomes.setdefault(test, set()).add(result)
    return tuple(test for test, seen in outcomes.items() if len(seen) == 2)


def classify_text(text: str) -> tuple[str, float]:
    """The shared error table, plus foundation-only classes when it finds nothing.

    The shared table reads "timed out" as a flaky test. Without an explicit flaky or
    intermittent marker that is a timeout: a hang and a slow runner both need a person.
    """
    error_class, confidence = classify_error(text)
    if error_class == "FLAKY_TEST" and _TIMED_OUT_RE.search(text) and not _EXPLICITLY_FLAKY_RE.search(text):
        return "TIMEOUT", confidence
    if error_class != "UNKNOWN":
        return error_class, confidence
    for fallback_class, pattern in _FALLBACK_PATTERNS:
        if pattern.search(text):
            return fallback_class, 0.9
    return error_class, confidence

# Secret and vulnerability scanners outrank everything: a leaked credential is never a lint fix.
SECURITY_TOOL_RE = re.compile(r"(?i)gitleaks|trufflehog|codeql|trivy|bandit|semgrep|snyk|grype|secret[- ]?scan")
# Scanners also report success ("no leaks found", "No known vulnerabilities found"); those must not match.
SECURITY_MESSAGE_RE = re.compile(
    r"(?i)(?<!no )(?<!no known )(?<!\b0 )(?:leaks? (?:detected|found)|secrets? detected|vulnerabilit(?:y|ies) found)"
)

# Linters and type checkers print the source they flag, so an identifier such as
# ``DependencyResolver`` in their log is not an environment failure. Test steps are
# deliberately excluded: a missing module in pytest output must stay a dependency failure.
_SOURCE_QUOTING_STEPS = frozenset({"lint", "formatting", "typing"})


def classify_ci_step(workflow: str, job: str, failed_step: str, log_excerpt: str) -> str:
    """Map common Actions job/step names to stable classes; unknown stays unknown."""
    haystack = f"{workflow} {job} {failed_step} {log_excerpt}".lower()
    if "ruff" in haystack or "flake8" in haystack or "lint" in haystack:
        return "lint"
    if "black" in haystack or "format" in haystack:
        return "formatting"
    if "mypy" in haystack or "pyright" in haystack or "type check" in haystack:
        return "typing"
    if "workflow" in haystack and ("yaml" in haystack or "syntax" in haystack):
        return "workflow_syntax"
    if "pytest" in haystack or "test" in failed_step.lower():
        return "unit_test_failure"
    return "unknown"


class FailureClassifier:
    """Heuristic, uncalibrated classifier that maps a failure event to a failure category."""

    def classify(self, event: FailureEvent) -> FailureClassification:
        """Classify a failure event from its message, log excerpt and Actions workflow, job and step names.

        Security scanner signals outrank every other signal. An unknown category recommends
        escalation.
        """
        msg_class, msg_conf = classify_text(event.message or event.log_excerpt)
        log_class, log_conf = classify_text(event.log_excerpt) if event.message else (msg_class, msg_conf)
        step_class = classify_ci_step(
            event.workflow, event.job, event.failed_step, event.log_excerpt or event.message
        )
        # Only the failing step's own name may override a log-only environment match; the job
        # name and log text are not trusted (a "lint" job can fail in its pip install step).
        named_step = classify_ci_step("", "", event.failed_step, "")
        repeated = intermittent_tests(event.log_excerpt)
        security = (
            msg_class == "SECURITY_ERROR"
            or SECURITY_TOOL_RE.search(f"{event.workflow} {event.job} {event.failed_step}")
            or SECURITY_MESSAGE_RE.search(f"{event.message}\n{event.log_excerpt}")
        )
        if security:
            category = "security_scan_failure"
            confidence = max(msg_conf, 0.8)
            evidence = ("security_scan", f"message={msg_class}", f"actions={step_class}")
        elif (
            event.message
            and msg_class not in ENVIRONMENT_CLASSES
            and log_class in ENVIRONMENT_CLASSES
            and named_step in _SOURCE_QUOTING_STEPS
        ):
            category = _MAP[named_step]
            confidence = 0.7
            evidence = (f"step={named_step}", f"message={msg_class}", f"log={log_class}:quoted_source")
        elif msg_class in ENVIRONMENT_CLASSES or log_class in ENVIRONMENT_CLASSES:
            env_class = msg_class if msg_class in ENVIRONMENT_CLASSES else log_class
            category = _MAP[env_class]
            confidence = msg_conf if env_class == msg_class else log_conf
            evidence = (f"message={msg_class}", f"log={log_class}", f"actions={step_class}")
        elif msg_class == "FLAKY_TEST" or repeated:
            category = "flaky_failure"
            confidence = max(msg_conf, 0.85)
            evidence = (f"message={msg_class}", f"actions={step_class}") + tuple(
                f"passed_and_failed={test}" for test in repeated[:3]
            )
        elif step_class != "unknown":
            category = _MAP.get(step_class, "unknown")
            confidence = max(msg_conf, 0.7)
            evidence = (f"actions={step_class}", f"message={msg_class}")
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

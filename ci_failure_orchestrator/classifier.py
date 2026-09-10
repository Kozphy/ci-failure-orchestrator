"""Error message classification for CI failure analysis.

This module provides pattern-based error message classification to categorize
CI failures into error types such as type errors, dependency errors, build errors,
test assertions, and more. Classification is heuristic and uses regex pattern
matching on normalized error messages.
"""

from __future__ import annotations

import re


PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("TYPE_ERROR", (r"incompatible type", r"mypy", r"type error", r"cannot assign")),
    ("DEPENDENCY_ERROR", (r"module not found", r"no module named", r"dependency", r"package .* not found")),
    ("BUILD_ERROR", (r"build failed", r"compilation failed", r"compiler error")),
    ("TEST_ASSERTION", (r"assertionerror", r"tests? failed", r"expected .* got")),
    ("FLAKY_TEST", (r"flaky", r"timed out", r"intermittent")),
    ("PACKAGE_ERROR", (r"artifact not found", r"package failed", r"wheel .* not found")),
    ("DEPLOYMENT_ERROR", (r"deploy(?:ment)? failed", r"rollout failed", r"release failed")),
    ("NETWORK_ERROR", (r"connection reset", r"dns", r"network unreachable", r"connection refused")),
    ("SECURITY_ERROR", (r"vulnerabilit", r"security scan failed", r"secret detected")),
    ("RUNTIME_ERROR", (r"runtimeerror", r"500 internal server error", r"smoke test failed")),
]


def classify_error(message: str) -> tuple[str, float]:
    """Classify an error message into an error type with confidence.

    This function normalizes the error message and matches it against predefined
    regex patterns to determine the error type. If no pattern matches, the
    error is classified as UNKNOWN with low confidence.

    Args:
        message: Error message to classify.

    Returns:
        Tuple of (error_type, confidence) where error_type is a string identifier
        and confidence is a float between 0.0 and 1.0.

    Classification Rules:
        - TYPE_ERROR: Type checking errors (mypy, incompatible types)
        - DEPENDENCY_ERROR: Missing modules or dependencies
        - BUILD_ERROR: Compilation or build failures
        - TEST_ASSERTION: Test assertion failures
        - FLAKY_TEST: Intermittent or timeout-related test failures
        - PACKAGE_ERROR: Artifact or package resolution failures
        - DEPLOYMENT_ERROR: Deployment or rollout failures
        - NETWORK_ERROR: Network connectivity issues
        - SECURITY_ERROR: Security scan or secret detection failures
        - RUNTIME_ERROR: Runtime errors during execution
        - UNKNOWN: No pattern matched (default)

    Side Effects:
        - None (pure classification logic).

    Audit Notes:
        - Incorrect classification may lead to inappropriate repair strategies.
        - Pattern matching is heuristic and may miss edge cases.
        - Recovery: Review classification results and add patterns if accuracy is poor.
        - Evidence: All classifications include error type and confidence for audit.

    Engineering Notes:
        - Trade-off: Pattern matching is fast but may not capture all error variations.
        - Design: Case-insensitive matching for robustness against message formatting.
        - Performance: Simple regex matching is O(n) where n is the number of patterns.
    """
    normalized = message.lower()
    for error_type, patterns in PATTERNS:
        for pattern in patterns:
            if re.search(pattern, normalized):
                return error_type, 0.9
    return "UNKNOWN", 0.35

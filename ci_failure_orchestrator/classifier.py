from __future__ import annotations

"""Error classification for CI failure messages.

This module provides regex-based classification of error messages
into standardized error types. It enables consistent categorization
and routing of failures throughout the repair workflow.

Module responsibility:
    - Define error type patterns for classification
    - Classify error messages into standardized types
    - Return confidence scores for each classification

Key invariants:
    - Classification is case-insensitive
    - Pattern matching is regex-based
    - First matching pattern wins
    - UNKNOWN is returned for unmatched messages

Safety boundaries:
    - Pattern list is fixed and ordered by specificity
    - No external dependencies or mutations
    - Classification is deterministic for the same input

Audit Notes:
    - Pattern order matters: more specific patterns should come first
    - Confidence scores are hardcoded (0.9 for matched, 0.35 for UNKNOWN)
    - Classification affects ranking, policy, and escalation behavior
"""

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
    """Classify an error message into a standard error type.

    Matches the message against a list of regex patterns. Returns the
    first matching error type with a confidence score of 0.9. If no
    pattern matches, returns ("UNKNOWN", 0.35).

    Args:
        message: The error message string to classify

    Returns:
        Tuple of (error_type, confidence) where:
        - error_type: One of the defined error types or "UNKNOWN"
        - confidence: 0.9 for matched patterns, 0.35 for UNKNOWN

    Side effects:
        None.

    Audit Notes:
        - First matching pattern determines the error type
        - Case-insensitive matching (message is lowercased)
        - UNKNOWN classification has lower confidence (0.35)
    """

    normalized = message.lower()
    for error_type, patterns in PATTERNS:
        for pattern in patterns:
            if re.search(pattern, normalized):
                return error_type, 0.9
    return "UNKNOWN", 0.35

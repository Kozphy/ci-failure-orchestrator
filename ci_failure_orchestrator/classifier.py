from __future__ import annotations

import re


PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("TYPE_ERROR", (r"incompatible type", r"mypy", r"type error", r"cannot assign")),
    ("BUILD_ERROR", (r"build failed", r"compilation failed", r"compiler error")),
    ("NETWORK_ERROR", (r"connection reset", r"dns", r"network unreachable", r"connection refused")),
    ("DEPENDENCY_ERROR", (r"module not found", r"no module named", r"dependency", r"package .* not found")),
    ("TEST_ASSERTION", (r"assertionerror", r"tests? failed", r"expected .* got")),
    ("FLAKY_TEST", (r"flaky", r"timed out", r"intermittent")),
    ("PACKAGE_ERROR", (r"artifact not found", r"package failed", r"wheel .* not found")),
    ("DEPLOYMENT_ERROR", (r"deploy(?:ment)? failed", r"rollout failed", r"release failed")),
    ("SECURITY_ERROR", (r"vulnerabilit", r"security scan failed", r"secret detected")),
    ("RUNTIME_ERROR", (r"runtimeerror", r"500 internal server error", r"smoke test failed")),
]


def classify_error(message: str) -> tuple[str, float]:
    normalized = message.lower()
    for error_type, patterns in PATTERNS:
        for pattern in patterns:
            if re.search(pattern, normalized):
                return error_type, 0.9
    return "UNKNOWN", 0.35

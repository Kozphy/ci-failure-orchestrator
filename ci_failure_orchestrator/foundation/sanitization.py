"""Context sanitization — defense-in-depth, not a guarantee of secret removal."""

from __future__ import annotations

import re

# Stable placeholders per the Phase 3 spec.
REDACTED = "[REDACTED_SECRET]"

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bearer", re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{8,}")),
    ("github_token", re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("assignment", re.compile(
        r"(?i)(api[_-]?key|password|secret|token|authorization)(\s*[:=]\s*)([^\s,;'\"\n]+)"
    )),
    ("connection", re.compile(
        r"(?i)(postgres|mysql|mongodb|redis)://[^\s]+"
    )),
    ("private_key", re.compile(
        r"-----BEGIN(?: RSA| OPENSSH| EC)? PRIVATE KEY-----[\s\S]*?-----END(?: RSA| OPENSSH| EC)? PRIVATE KEY-----"
    )),
)


def sanitize_text(text: str) -> tuple[str, int]:
    """Redact common secret patterns. Returns (cleaned, redaction_count).

    This is defense-in-depth. It does **not** guarantee all secrets are removed.
    """

    if not text:
        return text, 0
    cleaned = text
    count = 0
    for name, pattern in _PATTERNS:
        def _sub(match: re.Match[str], _name: str = name) -> str:
            nonlocal count
            count += 1
            if _name == "assignment":
                return f"{match.group(1)}{match.group(2)}{REDACTED}"
            if _name == "bearer":
                return f"Bearer {REDACTED}"
            return REDACTED

        cleaned, n = pattern.subn(_sub, cleaned)
        # count already incremented in _sub; n is for sanity
        del n
    return cleaned, count


def is_binary_noise(text: str) -> bool:
    """Reject clearly non-textual blobs from context."""

    if not text:
        return False
    if "\x00" in text:
        return True
    sample = text[:4000]
    if not sample:
        return False
    printable = sum(1 for ch in sample if ch.isprintable() or ch in "\n\r\t")
    return (printable / len(sample)) < 0.7

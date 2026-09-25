"""Provider prompt construction (sanitized; sensitive files never included)."""

from __future__ import annotations

from collections.abc import Sequence

from ..foundation.policy import FileCategory, classify_file
from ..foundation.sanitization import sanitize_text
from .common import MAX_FEEDBACK_CHARS, MAX_LOG_CHARS, git, tail
from .ingest import related_tracked_paths
from .session import FixSession
from .untrusted import UNTRUSTED_NOTICE, neutralize, untrusted_block

_MAX_TRACKED_LISTED = 400
_MAX_RELEVANT_FILES = 6
_MAX_FILE_CHARS = 16_000
_SMALL_REPO_FILES = 50
_SENSITIVE_CATEGORIES = frozenset({FileCategory.SECURITY})


def _read_base_file(session: FixSession, path: str) -> str | None:
    shown = git(session.repo, "show", f"{session.base_commit}:{path}")
    if shown.returncode != 0 or "\x00" in shown.stdout:
        return None
    return shown.stdout


def build_prompt(session: FixSession, *, attempt_number: int, changed_paths: Sequence[str]) -> str:
    failure = session.failure
    parts: list[str] = [
        "You are fixing a failing CI check in a git repository.",
        "Respond with exactly one unified diff in git format (paths relative to the repository root,",
        "using a/ and b/ prefixes) inside a single ```diff fenced block, followed by one line that",
        "starts with 'Rationale:'.",
        "Rules: make the smallest change that makes the verification commands pass; context lines must",
        "match the file contents shown below exactly; do not modify CI workflows, secrets, credentials",
        "or dependency manifests unless the failure clearly requires it.",
        UNTRUSTED_NOTICE,
        "",
        untrusted_block(
            "failure metadata",
            "\n".join(
                f"{label}: {neutralize(str(failure.get(key, '')))}"
                for label, key in (
                    ("workflow", "workflow"),
                    ("job", "job"),
                    ("failed step", "failed_step"),
                    ("message", "message"),
                )
            ),
        ),
    ]
    log = neutralize(str(failure.get("log_excerpt") or ""))
    if log:
        parts += ["", untrusted_block("CI log excerpt (tail)", tail(log, MAX_LOG_CHARS))]

    failing_baseline = next((s for s in session.baseline if not s.passed), None)
    if failing_baseline is not None and failure.get("source") != "local_reproduction":
        output = neutralize(f"{failing_baseline.stdout}\n{failing_baseline.stderr}".strip())
        parts += [
            "",
            untrusted_block(
                f"local reproduction at base commit (step {failing_baseline.name}, exit {failing_baseline.returncode})",
                tail(output, MAX_FEEDBACK_CHARS),
            ),
        ]

    parts += ["", "## Verification commands (all must pass after your patch)"]
    parts += [f"- {c.display}" for c in session.commands]

    for item in session.feedback[-2:]:
        parts += [
            "",
            f"## Previous attempt {item['attempt']} failed: {item['reason']}",
            "Do not repeat that patch.",
        ]
        if item.get("output"):
            parts += [untrusted_block(f"output of attempt {item['attempt']}", neutralize(item["output"]))]

    tracked = session.tracked_files
    listed = tracked[:_MAX_TRACKED_LISTED]
    parts += ["", f"## Tracked files ({len(tracked)} total, first {len(listed)} shown)"]
    parts += list(listed)

    tracked_set = set(tracked)
    candidates: dict[str, None] = {}
    for path in changed_paths:
        normalized = path.replace("\\", "/")
        if normalized in tracked_set:
            candidates.setdefault(normalized, None)
    for item in session.feedback[-1:]:
        for path in related_tracked_paths(item.get("output", ""), tracked):
            candidates.setdefault(path, None)
    if not candidates and len(tracked) <= _SMALL_REPO_FILES:
        for path in tracked:
            if classify_file(path) in (FileCategory.SOURCE, FileCategory.TEST):
                candidates.setdefault(path, None)
    shown = 0
    redacted_any = False
    for path in candidates:
        if shown >= _MAX_RELEVANT_FILES:
            break
        if classify_file(path) in _SENSITIVE_CATEGORIES:
            continue
        content = _read_base_file(session, path)
        if content is None:
            continue
        cleaned, redactions = sanitize_text(content[:_MAX_FILE_CHARS])
        redacted_any = redacted_any or redactions > 0
        truncated = " (truncated)" if len(content) > _MAX_FILE_CHARS else ""
        parts += ["", untrusted_block(f"file {path}{truncated}", cleaned)]
        shown += 1
    if redacted_any:
        parts += [
            "",
            "Note: lines containing [REDACTED_SECRET] were altered for safety; do not use them as diff context.",
        ]
    parts += ["", f"(attempt {attempt_number})"]
    prompt, _ = sanitize_text("\n".join(parts))
    return prompt


def extract_rationale(text: str) -> str:
    for line in reversed(text.replace("\r\n", "\n").split("\n")):
        stripped = line.strip()
        if stripped.lower().startswith("rationale:"):
            return stripped.split(":", 1)[1].strip()[:500]
    return ""

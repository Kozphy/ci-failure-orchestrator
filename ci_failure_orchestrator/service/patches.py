"""Unified-diff extraction and header parsing (file lists are never trusted from the proposer)."""

from __future__ import annotations

import re

from ..foundation.sanitization import contains_high_confidence_secret

_DIFF_LINE_PREFIXES = (
    "diff ",
    "index ",
    "--- ",
    "+++ ",
    "@@",
    " ",
    "+",
    "-",
    "\\",
    "new file mode",
    "deleted file mode",
    "old mode",
    "new mode",
    "similarity index",
    "dissimilarity index",
    "rename from",
    "rename to",
    "copy from",
    "copy to",
    "Binary files",
)
_FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*[^\n]*\n(.*?)```", re.DOTALL)
_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_MODE_LINE_RE = re.compile(r"^(?:new file mode|deleted file mode|old mode|new mode) (\d{6})\s*$")
_INDEX_MODE_RE = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+ (\d{6})\s*$")
_RENAME_COPY_RE = re.compile(r"^(?:rename|copy) (?:from|to) (.+)$")
_SYMLINK_MODE = "120000"
_SUBMODULE_MODE = "160000"


def decode_patch_bytes(raw: bytes) -> str:
    # PowerShell 5 redirection (`git diff > fix.patch`) writes UTF-16 with a BOM.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


def _looks_like_diff(text: str) -> bool:
    return ("diff --git " in text or ("--- " in text and "+++ " in text)) and "@@" in text


def _trim_trailing_non_diff(lines: list[str]) -> list[str]:
    end = len(lines)
    while end > 0 and (not lines[end - 1].strip() or not lines[end - 1].startswith(_DIFF_LINE_PREFIXES)):
        end -= 1
    return lines[:end]


def extract_patch(text: str) -> str:
    """Extract a unified diff from free-form text (LLM output or a patch file).

    Prefers a fenced ```diff block; otherwise starts at the first diff header.
    Line endings are normalized to LF and the result ends with a newline.
    Returns "" when no diff is found.
    """

    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    body = ""
    for match in _FENCE_RE.finditer(normalized):
        if _looks_like_diff(match.group(1)):
            body = match.group(1)
            break
    if not body:
        lines = normalized.split("\n")
        for idx, line in enumerate(lines):
            if line.startswith("diff --git ") or (
                line.startswith("--- ") and idx + 1 < len(lines) and lines[idx + 1].startswith("+++ ")
            ):
                body = "\n".join(lines[idx:])
                break
    if not body or not _looks_like_diff(body):
        return ""
    kept = _trim_trailing_non_diff(body.split("\n"))
    return "\n".join(kept) + "\n" if kept else ""


def _strip_prefix(path: str, prefix: str) -> str:
    path = path.split("\t", 1)[0].strip()
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    return path.removeprefix(prefix)


def parse_patch_files(patch: str) -> tuple[str, ...]:
    """Files touched by a unified diff, derived from its headers (never trusted from the proposer)."""

    files: dict[str, None] = {}
    lines = patch.split("\n")
    for idx, line in enumerate(lines):
        if line.startswith("diff --git "):
            match = _DIFF_GIT_RE.match(line)
            if match:
                files.setdefault(match.group(1), None)
                files.setdefault(match.group(2), None)
        elif line.startswith("--- ") and idx + 1 < len(lines) and lines[idx + 1].startswith("+++ "):
            old = _strip_prefix(line[4:], "a/")
            new = _strip_prefix(lines[idx + 1][4:], "b/")
            for path in (old, new):
                if path and path != "/dev/null":
                    files.setdefault(path, None)
    return tuple(files)


def added_files(patch: str) -> tuple[str, ...]:
    out: list[str] = []
    lines = patch.split("\n")
    for idx, line in enumerate(lines):
        if line.startswith("--- /dev/null") and idx + 1 < len(lines) and lines[idx + 1].startswith("+++ "):
            out.append(_strip_prefix(lines[idx + 1][4:], "b/"))
    return tuple(out)


def is_unsafe_path(path: str) -> bool:
    p = path.replace("\\", "/")
    return not p or p.startswith("/") or re.match(r"^[A-Za-z]:", p) is not None or ".." in p.split("/")


def patch_violation(patch: str) -> str | None:
    """First structural reason to refuse a patch before it reaches any worktree, or None.

    Codes are chosen so the foundation retry engine treats them as unrecoverable
    (``forbidden_path*``, ``binary_patch_rejected``, ``invalid*``).
    """

    lines = patch.split("\n")
    paths = list(parse_patch_files(patch))
    for line in lines:
        mode = _MODE_LINE_RE.match(line) or _INDEX_MODE_RE.match(line)
        if mode and mode.group(1) == _SYMLINK_MODE:
            return "forbidden_path_symlink"
        if mode and mode.group(1) == _SUBMODULE_MODE:
            return "forbidden_path_submodule"
        if line.startswith(("GIT binary patch", "Binary files ")):
            return "binary_patch_rejected"
        if line[1:].startswith("Subproject commit "):
            return "forbidden_path_submodule"
        renamed = _RENAME_COPY_RE.match(line)
        if renamed:
            paths.append(_strip_prefix(renamed.group(1), ""))
    for path in paths:
        if is_unsafe_path(path):
            return "forbidden_path_outside_repo"
        if ".git" in path.replace("\\", "/").split("/"):
            return "forbidden_path_git_dir"
    added = "\n".join(line[1:] for line in lines if line.startswith("+") and not line.startswith("+++"))
    if contains_high_confidence_secret(added):
        return "invalid_patch_contains_secret"
    return None

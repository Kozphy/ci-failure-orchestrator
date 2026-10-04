"""Deterministic detection of patches that make CI pass by weakening verification.

A patch can turn a red pipeline green without fixing anything: delete or skip the failing
test, loosen its assertion, lower a coverage threshold, mark a CI step as allowed to fail,
or swallow the exception in production code. Those patches pass every sandbox check, so
the policy gate needs a signal that does not come from running the checks themselves.

The analysis is line-based over the unified diff. It errs toward flagging: a refactor that
merges two assertions into one is reported as an assertion removal. It does not parse code,
so a weakening spread across files or hidden behind a helper function is not detected.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from .sanitization import sanitize_text


class IntegritySeverity(str, Enum):
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class IntegrityCode(str, Enum):
    TEST_FILE_DELETED = "TEST_FILE_DELETED"
    TEST_CASE_REMOVED = "TEST_CASE_REMOVED"
    TEST_SKIPPED = "TEST_SKIPPED"
    TEST_FOCUSED = "TEST_FOCUSED"
    TEST_DESELECTED = "TEST_DESELECTED"
    ASSERTION_REMOVED = "ASSERTION_REMOVED"
    ASSERTION_WEAKENED = "ASSERTION_WEAKENED"
    TEST_RESULT_OVERRIDDEN = "TEST_RESULT_OVERRIDDEN"
    COVERAGE_THRESHOLD_LOWERED = "COVERAGE_THRESHOLD_LOWERED"
    CI_CONFIG_DELETED = "CI_CONFIG_DELETED"
    CI_CHECK_REMOVED = "CI_CHECK_REMOVED"
    CI_FAILURE_IGNORED = "CI_FAILURE_IGNORED"
    QUALITY_GATE_DISABLED = "QUALITY_GATE_DISABLED"
    REVIEW_CONTROL_MODIFIED = "REVIEW_CONTROL_MODIFIED"
    EXCEPTION_SWALLOWED = "EXCEPTION_SWALLOWED"
    TEST_ENVIRONMENT_SPECIAL_CASE = "TEST_ENVIRONMENT_SPECIAL_CASE"
    # Escalate: legitimate in some repairs, but a person must confirm the reason.
    TEST_EXPECTATION_CHANGED = "TEST_EXPECTATION_CHANGED"
    CHECK_SUPPRESSED_INLINE = "CHECK_SUPPRESSED_INLINE"
    CI_ENVIRONMENT_BRANCH = "CI_ENVIRONMENT_BRANCH"


_SEVERITY: dict[IntegrityCode, IntegritySeverity] = {
    code: IntegritySeverity.REJECT for code in IntegrityCode
} | {
    IntegrityCode.TEST_EXPECTATION_CHANGED: IntegritySeverity.ESCALATE,
    IntegrityCode.CHECK_SUPPRESSED_INLINE: IntegritySeverity.ESCALATE,
    IntegrityCode.CI_ENVIRONMENT_BRANCH: IntegritySeverity.ESCALATE,
}

_MESSAGES: dict[IntegrityCode, str] = {
    IntegrityCode.TEST_FILE_DELETED: "test file deleted",
    IntegrityCode.TEST_CASE_REMOVED: "test cases removed",
    IntegrityCode.TEST_SKIPPED: "test skip or xfail marker added",
    IntegrityCode.TEST_FOCUSED: "focused test (.only) added; other tests stop running",
    IntegrityCode.TEST_DESELECTED: "tests excluded from collection",
    IntegrityCode.ASSERTION_REMOVED: "assertions removed from tests",
    IntegrityCode.ASSERTION_WEAKENED: "strict assertion replaced by a weaker one",
    IntegrityCode.TEST_RESULT_OVERRIDDEN: "test runner exit status forced",
    IntegrityCode.COVERAGE_THRESHOLD_LOWERED: "coverage threshold lowered or removed",
    IntegrityCode.CI_CONFIG_DELETED: "CI configuration file deleted",
    IntegrityCode.CI_CHECK_REMOVED: "verification command removed from CI",
    IntegrityCode.CI_FAILURE_IGNORED: "CI step allowed to fail",
    IntegrityCode.QUALITY_GATE_DISABLED: "lint, type or security check disabled in configuration",
    IntegrityCode.REVIEW_CONTROL_MODIFIED: "code review controls modified",
    IntegrityCode.EXCEPTION_SWALLOWED: "broad exception silently swallowed in production code",
    IntegrityCode.TEST_ENVIRONMENT_SPECIAL_CASE: "production code behaves differently under the test runner",
    IntegrityCode.TEST_EXPECTATION_CHANGED: "existing test expectation changed",
    IntegrityCode.CHECK_SUPPRESSED_INLINE: "inline lint, type or security suppression added",
    IntegrityCode.CI_ENVIRONMENT_BRANCH: "production code branches on the CI environment",
}

_MAX_EVIDENCE_CHARS = 160


@dataclass(frozen=True)
class IntegrityFinding:
    code: IntegrityCode
    path: str
    evidence: str = ""

    @property
    def severity(self) -> IntegritySeverity:
        return _SEVERITY[self.code]

    @property
    def message(self) -> str:
        return _MESSAGES[self.code]

    def describe(self) -> str:
        suffix = f": {self.evidence}" if self.evidence else ""
        return f"{self.code.value} {self.path}{suffix}"


@dataclass
class FileDiff:
    path: str
    deleted: bool = False
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    # Hunk lines in order as (marker, text) so multi-line constructs can be inspected.
    lines: list[tuple[str, str]] = field(default_factory=list)


_HUNK_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def _strip_prefix(path: str) -> str:
    path = path.strip().split("\t", 1)[0]
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def parse_unified_diff(patch: str) -> list[FileDiff]:
    """Split a unified diff into per-file added/removed lines.

    Hunk line counts decide where a hunk ends, so a removed line that itself starts with
    ``--`` is not mistaken for a file header.
    """
    files: list[FileDiff] = []
    current: FileDiff | None = None
    in_hunk = False
    counted = False
    old_left = new_left = 0
    pending_old: str | None = None
    git_header = False

    for raw in (patch or "").splitlines():
        if in_hunk and counted and old_left <= 0 and new_left <= 0:
            in_hunk = False
        if in_hunk and current is not None:
            if raw.startswith("\\"):
                continue
            # Without hunk counts the end of a hunk can only be guessed from the next header.
            header_like = not counted and raw.startswith(("diff --git ", "@@", "--- a/", "+++ b/", "--- /dev/null"))
            marker = raw[:1] or " "
            if marker in "+- " and not header_like:
                text = raw[1:]
                if marker == "+":
                    current.added.append(text)
                    new_left -= 1
                elif marker == "-":
                    current.removed.append(text)
                    old_left -= 1
                else:
                    old_left -= 1
                    new_left -= 1
                current.lines.append((marker, text))
                continue
            in_hunk = False

        if raw.startswith("diff --git "):
            parts = raw.split(" ")
            current = FileDiff(path=_strip_prefix(parts[-1]) if len(parts) >= 4 else "")
            files.append(current)
            pending_old = None
            git_header = True
        elif raw.startswith("deleted file mode") and current is not None:
            current.deleted = True
        elif raw.startswith("--- "):
            pending_old = _strip_prefix(raw[4:])
        elif raw.startswith("+++ "):
            new_path = _strip_prefix(raw[4:])
            deleted = new_path == "/dev/null"
            path = (pending_old or "") if deleted else new_path
            if current is None or not git_header:
                current = FileDiff(path=path)
                files.append(current)
            elif path:
                current.path = path
            current.deleted = current.deleted or deleted
            git_header = False
        elif raw.startswith("@@"):
            if current is None:
                current = FileDiff(path="")
                files.append(current)
            m = _HUNK_RE.match(raw)
            counted = m is not None
            if m:
                old_left = int(m.group(1)) if m.group(1) is not None else 1
                new_left = int(m.group(2)) if m.group(2) is not None else 1
            in_hunk = True
            git_header = False
    return files


def _norm(path: str) -> str:
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lower()


_TEST_BASENAME_RE = re.compile(
    r"^(test_.*\.py|.*_test\.(py|go)|conftest\.py|.*\.(test|spec)\.[cm]?[jt]sx?"
    r"|.*tests?\.(java|kt|cs)|.*_spec\.rb)$"
)
_TEST_DIRS = ("tests", "test", "__tests__", "spec", "testing")


def is_test_path(path: str) -> bool:
    p = _norm(path)
    segments = p.split("/")
    return bool(_TEST_BASENAME_RE.match(segments[-1])) or any(s in _TEST_DIRS for s in segments[:-1])


_CI_BASENAMES = frozenset(
    {"jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml", "bitbucket-pipelines.yml", ".travis.yml"}
)


def is_ci_path(path: str) -> bool:
    p = _norm(path)
    return (
        p.startswith((".github/workflows/", ".circleci/"))
        or p.rsplit("/", 1)[-1] in _CI_BASENAMES
    )


_BUILD_SCRIPT_BASENAMES = frozenset({"makefile", "justfile", "tox.ini", "noxfile.py", "package.json"})


def _is_build_script(path: str) -> bool:
    base = _norm(path).rsplit("/", 1)[-1]
    return is_ci_path(path) or base in _BUILD_SCRIPT_BASENAMES or base.endswith((".sh", ".ps1"))


_QUALITY_CONFIG_RE = re.compile(
    r"^(pyproject\.toml|setup\.cfg|tox\.ini|\.flake8|\.?ruff\.toml|\.?mypy\.ini|pytest\.ini"
    r"|\.coveragerc|\.pre-commit-config\.ya?ml|tsconfig.*\.json|\.eslintrc.*|eslint\.config\..*"
    r"|(jest|vitest)\.config\..*|package\.json|codecov\.ya?ml|\.golangci\.ya?ml|\.bandit)$"
)


def _is_quality_config(path: str) -> bool:
    return bool(_QUALITY_CONFIG_RE.match(_norm(path).rsplit("/", 1)[-1]))


_REVIEW_CONTROL_RE = re.compile(r"(^|/)(codeowners|\.github/settings\.ya?ml|\.github/rulesets/.*)$")

_SOURCE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".java", ".kt", ".cs", ".rb", ".rs")


def _is_production_source(path: str) -> bool:
    return _norm(path).endswith(_SOURCE_SUFFIXES) and not is_test_path(path)


def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns))


_TEST_DEF = _rx(
    r"^\s*(async\s+)?def\s+test\w*\s*\(",
    r"^\s*func\s+Test\w*\s*\(",
    r"^\s*(it|test)\s*\(\s*['\"`]",
    r"@Test\b",
)
_SKIP = _rx(
    r"pytest\.mark\.(skip|skipif|xfail)\b",
    r"\bpytest\.(skip|xfail|importorskip)\s*\(",
    r"\bunittest\.(skip|skipIf|skipUnless|expectedFailure)\b",
    r"^\s*@(skip|skipIf|skipUnless|expectedFailure)\b",
    r"\.skipTest\s*\(",
    r"\b(it|describe|test|context)\.(skip|todo)\s*\(",
    r"^\s*x(it|describe|test)\s*\(",
    r"@(Disabled|Ignore)\b",
    r"\bt\.Skip(f|Now)?\s*\(",
)
_FOCUS = _rx(r"\b(it|describe|test|context)\.only\s*\(", r"^\s*f(it|describe)\s*\(")
_DESELECT = _rx(
    r"--ignore(-glob)?[= ]",
    r"--deselect\b",
    r"\s-k\s+['\"]?not\b",
    r"\bcollect_ignore(_glob)?\b",
    r"\btestPathIgnorePatterns\b",
)
_ASSERTION = _rx(
    r"^\s*assert\b",
    r"\bself\.assert\w*\s*\(",
    r"\bexpect\s*\(",
    r"\b(assert|require)\.\w+\s*\(",
    r"\bassert(That|Equals|True|False|NotNull|Null|Throws)\s*\(",
    r"\bpytest\.raises\b",
    r"\bt\.(Error|Fatal)f?\s*\(",
)
_STRONG = _rx(
    r"[^=!<>]==[^=]",
    r"!=",
    r"\bassert\w*Equal\w*\s*\(",
    r"\bassert(Equals|Throws|Raises\w*|In|Is|IsInstance)\s*\(",
    r"\.(toEqual|toBe|toStrictEqual|toMatch\w*|toThrow\w*|toHaveBeenCalledWith|toContain)\s*\(",
    r"\bassert\.(Equal\w*|Exactly|ErrorIs|EqualError|Contains)\s*\(",
    r"\bpytest\.raises\b",
)
_TAUTOLOGY = re.compile(r"^\s*assert\s+(?P<lhs>[\w.]+)\s*==\s*(?P=lhs)\s*(#.*)?$")
_WEAK = _rx(
    r"\bis\s+not\s+None\b",
    r"^\s*assert\s+(True|1|not\s+None)\s*(#.*)?$",
    r"^\s*assert\s+[\w.]+\s*(#.*)?$",
    _TAUTOLOGY.pattern,
    r"\bassert(IsNotNone|NotNull)\s*\(",
    r"\bassertTrue\s*\(\s*(True|1)\s*\)",
    r"\.(toBeDefined|toBeTruthy)\s*\(",
    r"\.not\.(toBeNull|toBeUndefined)\s*\(",
    r"\bassert\.(NotNil|NotEmpty)\s*\(",
)
_EXIT_OVERRIDE = _rx(r"\bexitstatus\s*=\s*0\b", r"\bos\._exit\s*\(", r"\bsys\.exit\s*\(\s*0?\s*\)")
_CI_IGNORE = _rx(
    r"\bcontinue-on-error:\s*true\b",
    r"\ballow_failure:\s*true\b",
    r"\|\|\s*(true|:|exit\s+0)\b",
    r"\bset\s+\+e\b",
    r"--exit-zero\b",
    r"^\s*if:\s*(false|\$\{\{\s*false\s*\}\})\s*$",
    r"^\s*when:\s*(never|manual)\s*$",
)
_CHECK_TOOL = re.compile(
    r"\b(pytest|tox|nox|unittest|jest|vitest|mocha|go test|go vet|cargo test|cargo clippy|"
    r"npm (?:run )?test|yarn test|pnpm test|mvn\b[^\n]*\b(?:test|verify)|gradlew? [^\n]*\b(?:test|check)|"
    r"ruff|flake8|pylint|mypy|pyright|eslint|tsc|golangci-lint|bandit|semgrep|codeql|trivy|gitleaks|"
    r"pip-audit|safety|npm audit|snyk|coverage)\b"
)
_GATE_DISABLED = re.compile(
    r"(?i:^\s*ignore_errors\s*=\s*true\b)"
    r"|(?i:^\s*strict\s*=\s*false\b)"
    r"|\"(strict|noImplicitAny|strictNullChecks)\"\s*:\s*false"
    r"|(^|\s)-p\s+no:"
)
_PRECOMMIT_HOOK = re.compile(r"^\s*-\s*id:\s*([\w.-]+)")
_THRESHOLD = (
    ("fail_under", re.compile(r"fail[_-]under\s*[=:]\s*(\d+(?:\.\d+)?)")),
    ("cov-fail-under", re.compile(r"--cov-fail-under[= ](\d+(?:\.\d+)?)")),
    ("minimum_coverage", re.compile(r"min(?:imum)?[_-]coverage\s*[=:]\s*(\d+(?:\.\d+)?)")),
)
_JEST_THRESHOLD = re.compile(r"[\"']?(branches|functions|lines|statements)[\"']?\s*:\s*(\d+(?:\.\d+)?)")
_INLINE_SUPPRESSION = _rx(
    r"#\s*noqa\b",
    r"#\s*type:\s*ignore\b",
    r"#\s*pyright:\s*ignore\b",
    r"#\s*pylint:\s*disable\b",
    r"#\s*nosec\b",
    r"#\s*nosemgrep\b",
    r"#\s*pragma:\s*no\s*cover\b",
    r"eslint-disable",
    r"@ts-(ignore|nocheck|expect-error)\b",
    r"//\s*nolint\b",
    r"@SuppressWarnings\b",
    r"\bNOSONAR\b",
)
_PY_BROAD_EXCEPT = re.compile(
    r"^\s*except\s*(\(?\s*(Exception|BaseException)\b[^:]*)?:\s*(?P<body>[^#]*?)\s*(#.*)?$"
)
_SWALLOW_BODY = re.compile(r"^(pass|\.\.\.|continue|return|return\s+None)$")
_SWALLOW_INLINE = _rx(
    r"\bcatch\s*(\(\s*\w*\s*(:\s*\w+)?\s*\))?\s*\{\s*\}",
    r"\bcatch\s*\(\s*(Exception|Throwable|RuntimeException)\s+\w+\s*\)\s*\{\s*\}",
    r"\bsuppress\s*\(\s*(Exception|BaseException)\s*\)",
)
_TEST_RUNNER_SNIFF = _rx(
    r"PYTEST_CURRENT_TEST",
    r"['\"]pytest['\"]\s+in\s+sys\.modules",
    r"sys\.modules\.get\(\s*['\"]pytest",
    r"process\.env\.(JEST_WORKER_ID|VITEST)\b",
    r"process\.env\.NODE_ENV\s*[!=]==?\s*['\"]test['\"]",
    r"\btesting\.Testing\(\)",
)
_CI_SNIFF = _rx(
    r"\bos\.(environ\.get|getenv)\(\s*['\"](CI|GITHUB_ACTIONS|GITLAB_CI|CIRCLECI)['\"]",
    r"\bos\.environ\[\s*['\"](CI|GITHUB_ACTIONS|GITLAB_CI|CIRCLECI)['\"]",
    r"['\"](CI|GITHUB_ACTIONS|GITLAB_CI|CIRCLECI)['\"]\s+in\s+os\.environ",
    r"process\.env\.(CI|GITHUB_ACTIONS|GITLAB_CI|CIRCLECI)\b",
)


def _count(lines: Iterable[str], pattern: re.Pattern[str]) -> int:
    return sum(1 for line in lines if pattern.search(line))


def _first(lines: Iterable[str], pattern: re.Pattern[str]) -> str:
    for line in lines:
        if pattern.search(line):
            return line
    return ""


def _evidence(line: str) -> str:
    text, _ = sanitize_text(line.strip())
    return text if len(text) <= _MAX_EVIDENCE_CHARS else text[: _MAX_EVIDENCE_CHARS - 3] + "..."


def _net_added(diff: FileDiff, pattern: re.Pattern[str]) -> tuple[int, str]:
    net = _count(diff.added, pattern) - _count(diff.removed, pattern)
    return net, _first(diff.added, pattern) if net > 0 else ""


def _thresholds(lines: list[str], use_jest_keys: bool) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {}
    for line in lines:
        for key, pattern in _THRESHOLD:
            for m in pattern.finditer(line):
                found.setdefault(key, []).append(float(m.group(1)))
        if use_jest_keys:
            for m in _JEST_THRESHOLD.finditer(line):
                found.setdefault(m.group(1), []).append(float(m.group(2)))
    return found


def _swallowing_excepts(diff: FileDiff) -> str:
    lines = diff.lines
    for i, (marker, text) in enumerate(lines):
        if marker != "+":
            continue
        m = _PY_BROAD_EXCEPT.match(text)
        if m:
            body = m.group("body").strip()
            if body:
                if _SWALLOW_BODY.match(body):
                    return text
                continue
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            if nxt and nxt[0] == "+" and _SWALLOW_BODY.match(nxt[1].strip()):
                return f"{text.strip()} {nxt[1].strip()}"
            continue
        if _SWALLOW_INLINE.search(text):
            return text
    return ""


_PROSE_SUFFIXES = (".md", ".rst", ".txt", ".adoc")


def _is_prose(path: str) -> bool:
    p = _norm(path)
    return p.endswith(_PROSE_SUFFIXES) or p.startswith("docs/")


def _analyze_file(diff: FileDiff) -> list[IntegrityFinding]:
    path = diff.path
    out: list[IntegrityFinding] = []
    if _is_prose(path):
        return out

    def flag(code: IntegrityCode, line: str = "") -> None:
        out.append(IntegrityFinding(code, path, _evidence(line)))

    test_file = is_test_path(path)
    ci_file = is_ci_path(path)
    quality_config = _is_quality_config(path)

    if _REVIEW_CONTROL_RE.search(_norm(path)):
        flag(IntegrityCode.REVIEW_CONTROL_MODIFIED)
    if diff.deleted and test_file:
        flag(IntegrityCode.TEST_FILE_DELETED)
        return out
    if diff.deleted and ci_file:
        flag(IntegrityCode.CI_CONFIG_DELETED)
        return out

    net, line = _net_added(diff, _SKIP)
    if net > 0:
        flag(IntegrityCode.TEST_SKIPPED, line)
    net, line = _net_added(diff, _FOCUS)
    if net > 0:
        flag(IntegrityCode.TEST_FOCUSED, line)
    net, line = _net_added(diff, _DESELECT)
    if net > 0:
        flag(IntegrityCode.TEST_DESELECTED, line)

    if test_file:
        if _count(diff.removed, _TEST_DEF) > _count(diff.added, _TEST_DEF):
            flag(IntegrityCode.TEST_CASE_REMOVED, _first(diff.removed, _TEST_DEF))
        removed_asserts = [ln for ln in diff.removed if _ASSERTION.search(ln)]
        added_asserts = [ln for ln in diff.added if _ASSERTION.search(ln)]
        if len(removed_asserts) > len(added_asserts):
            flag(IntegrityCode.ASSERTION_REMOVED, removed_asserts[0])

        def strong(lines: list[str]) -> int:
            return sum(1 for ln in lines if _STRONG.search(ln) and not _TAUTOLOGY.match(ln))

        if _count(added_asserts, _WEAK) > _count(removed_asserts, _WEAK) and strong(removed_asserts) > strong(
            added_asserts
        ):
            flag(IntegrityCode.ASSERTION_WEAKENED, _first(added_asserts, _WEAK))
        if removed_asserts:
            flag(IntegrityCode.TEST_EXPECTATION_CHANGED, removed_asserts[0])
        net, line = _net_added(diff, _EXIT_OVERRIDE)
        if net > 0:
            flag(IntegrityCode.TEST_RESULT_OVERRIDDEN, line)

    before = _thresholds(diff.removed, quality_config)
    after = _thresholds(diff.added, quality_config)
    for key, old_values in before.items():
        new_values = after.get(key)
        if not new_values or min(new_values) < max(old_values):
            flag(IntegrityCode.COVERAGE_THRESHOLD_LOWERED, _first(diff.removed, re.compile(re.escape(key))))
            break

    if _is_build_script(path):
        net, line = _net_added(diff, _CI_IGNORE)
        if net > 0:
            flag(IntegrityCode.CI_FAILURE_IGNORED, line)
    if ci_file:
        added_text = "\n".join(diff.added)
        for removed in diff.removed:
            m = _CHECK_TOOL.search(removed)
            if m and m.group(1) not in added_text:
                flag(IntegrityCode.CI_CHECK_REMOVED, removed)
                break

    if quality_config:
        net, line = _net_added(diff, _GATE_DISABLED)
        if net > 0:
            flag(IntegrityCode.QUALITY_GATE_DISABLED, line)
        kept = {m.group(1) for ln in diff.added if (m := _PRECOMMIT_HOOK.match(ln))}
        for ln in diff.removed:
            m = _PRECOMMIT_HOOK.match(ln)
            if m and m.group(1) not in kept:
                flag(IntegrityCode.QUALITY_GATE_DISABLED, ln)
                break

    net, line = _net_added(diff, _INLINE_SUPPRESSION)
    if net > 0:
        flag(IntegrityCode.CHECK_SUPPRESSED_INLINE, line)

    if _is_production_source(path):
        swallowed = _swallowing_excepts(diff)
        if swallowed:
            flag(IntegrityCode.EXCEPTION_SWALLOWED, swallowed)
        net, line = _net_added(diff, _TEST_RUNNER_SNIFF)
        if net > 0:
            flag(IntegrityCode.TEST_ENVIRONMENT_SPECIAL_CASE, line)
        net, line = _net_added(diff, _CI_SNIFF)
        if net > 0:
            flag(IntegrityCode.CI_ENVIRONMENT_BRANCH, line)
    return out


def analyze_patch(patch: str) -> tuple[IntegrityFinding, ...]:
    findings: list[IntegrityFinding] = []
    for diff in parse_unified_diff(patch):
        findings.extend(_analyze_file(diff))
    return tuple(findings)

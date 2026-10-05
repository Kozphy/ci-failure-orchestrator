"""Structured evidence from test-runner output: counts, failed tests, coverage, fingerprints.

Pytest output is parsed precisely: the short test summary (``FAILED``/``ERROR`` lines), the
``E`` lines, the final result line and the pytest-cov ``TOTAL`` row. Other runners fall back
to the exit code and the last error-looking line. That is enough to tell "still failing"
from "passing", but not which test failed, so comparisons that need test identities return
``None`` (unknown) rather than guessing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

PYTEST_TESTS_FAILED = 1
PYTEST_USAGE_ERROR = 4
PYTEST_NO_TESTS_COLLECTED = 5

_TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")
_SUMMARY_LINE = re.compile(r"^(?P<kind>FAILED|ERROR)\s+(?P<nodeid>\S+)(?:\s+-\s+(?P<detail>.*))?$")
_RESULT_LINE = re.compile(
    r"^=*\s*(?P<body>(?:\d+ [a-z]+(?:, )?)+|no tests ran) in [\d.]+s(?: \([^)]*\))?\s*=*$"
)
_RESULT_ITEM = re.compile(r"(\d+) ([a-z]+)")
_E_LINE = re.compile(r"^E\s+(?P<text>\S.*)$")
_EXCEPTION = re.compile(
    r"^(?P<exc>[A-Za-z_][\w.]*(?:Error|Exception|Failure|Interrupt|Exit|Warning|Timeout))\b:?\s*(?P<msg>.*)$"
)
_PYTEST_FRAME = re.compile(r"^(?P<file>[^\s:]+\.py):\d+: (?P<exc>[A-Za-z_][\w.]*)$")
_TRACEBACK_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line \d+')
_COVERAGE_TOTAL = re.compile(r"^TOTAL\s+.*?(?P<pct>\d+(?:\.\d+)?)%\s*$")

_COUNT_KEYS = {
    "passed": "passed",
    "failed": "failed",
    "error": "errors",
    "errors": "errors",
    "skipped": "skipped",
    "xfailed": "xfailed",
    "xpassed": "xpassed",
    "deselected": "deselected",
}


@dataclass(frozen=True)
class TestFailure:
    """Immutable record of one failed or erroring test and its exception, when known."""

    __test__ = False

    nodeid: str
    exception_type: str = ""
    message: str = ""


@dataclass(frozen=True)
class TestRunSummary:
    """Counts parsed from one or more test runs. ``parsed`` is False when no result line was found."""

    __test__ = False

    parsed: bool = False
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0
    deselected: int = 0
    failures: tuple[TestFailure, ...] = ()
    coverage_percent: float | None = None

    @property
    def total(self) -> int:
        """Tests that were collected and run (deselected tests are excluded)."""
        return self.passed + self.failed + self.errors + self.skipped + self.xfailed + self.xpassed

    @property
    def failed_ids(self) -> frozenset[str]:
        """Node IDs of the failed and erroring tests named in the output."""
        return frozenset(f.nodeid for f in self.failures)

    def to_dict(self) -> dict[str, Any]:
        """Return the counts, sorted failed test IDs and coverage as a JSON-friendly dict."""
        return {
            "parsed": self.parsed,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "xfailed": self.xfailed,
            "xpassed": self.xpassed,
            "deselected": self.deselected,
            "failed_tests": sorted(self.failed_ids),
            "coverage_percent": self.coverage_percent,
        }


def _lines(text: str) -> list[str]:
    return [_TIMESTAMP_PREFIX.sub("", line.rstrip()) for line in (text or "").splitlines()]


def _exception_of(detail: str) -> tuple[str, str]:
    detail = detail.strip()
    if detail.startswith("assert ") or detail == "assert":
        return "AssertionError", detail
    m = _EXCEPTION.match(detail)
    if m:
        return m.group("exc"), m.group("msg")
    return "", detail


def parse_test_output(text: str) -> TestRunSummary:
    """Parse pytest output into result counts, failed tests and pytest-cov total coverage.

    Failures without their own detail take the exception from the first ``E`` line.
    """
    lines = _lines(text)
    counts: dict[str, int] = {}
    parsed = False
    failures: dict[str, TestFailure] = {}
    coverage: float | None = None
    first_e = ""

    for line in lines:
        stripped = line.strip()
        if not first_e:
            m = _E_LINE.match(line)
            if m:
                first_e = m.group("text")
        m = _SUMMARY_LINE.match(stripped)
        if m:
            exc, msg = _exception_of(m.group("detail") or "")
            failures.setdefault(m.group("nodeid"), TestFailure(m.group("nodeid"), exc, msg))
            continue
        m = _RESULT_LINE.match(stripped)
        if m:
            parsed = True
            for number, word in _RESULT_ITEM.findall(m.group("body")):
                key = _COUNT_KEYS.get(word)
                if key:
                    counts[key] = counts.get(key, 0) + int(number)
            continue
        m = _COVERAGE_TOTAL.match(stripped)
        if m:
            coverage = float(m.group("pct"))

    if first_e:
        exc, msg = _exception_of(first_e)
        failures = {
            nodeid: (TestFailure(nodeid, exc, msg) if not f.exception_type and not f.message else f)
            for nodeid, f in failures.items()
        }
    return TestRunSummary(parsed=parsed, failures=tuple(failures.values()), coverage_percent=coverage, **counts)


def combine_summaries(summaries: Iterable[TestRunSummary]) -> TestRunSummary:
    """Merge several run summaries: counts are summed, failures deduplicated by node ID.

    The result is parsed only if every input was, and keeps the last known coverage.
    """
    items = list(summaries)
    if not items:
        return TestRunSummary()
    failures: dict[str, TestFailure] = {}
    for s in items:
        for f in s.failures:
            failures.setdefault(f.nodeid, f)
    coverage = next((s.coverage_percent for s in reversed(items) if s.coverage_percent is not None), None)
    return TestRunSummary(
        parsed=all(s.parsed for s in items),
        passed=sum(s.passed for s in items),
        failed=sum(s.failed for s in items),
        errors=sum(s.errors for s in items),
        skipped=sum(s.skipped for s in items),
        xfailed=sum(s.xfailed for s in items),
        xpassed=sum(s.xpassed for s in items),
        deselected=sum(s.deselected for s in items),
        failures=tuple(failures.values()),
        coverage_percent=coverage,
    )


_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_DIRS = re.compile(r"(?:[A-Za-z]:)?[\\/]?(?:[\w.-]+[\\/])+(?=[\w.-])")
_DURATION = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s)\b")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize_message(text: str, *, limit: int = 80) -> str:
    """Stable form of a failure message: no addresses, directories, durations or punctuation."""
    first = next((line.strip() for line in (text or "").splitlines() if line.strip()), "")
    first = _ADDRESS.sub("addr", first)
    first = _UUID.sub("uuid", first)
    first = _DIRS.sub("", first)
    first = _DURATION.sub("dur", first)
    return _NON_WORD.sub("_", first.lower()).strip("_")[:limit]


@dataclass(frozen=True)
class FailureFingerprint:
    """Immutable identity of a verification failure, used to tell repeated failures apart."""

    failure_class: str
    job: str = ""
    test: str = ""
    exception_type: str = ""
    message: str = ""
    frame: str = ""
    exit_code: int | None = None
    failed_tests: tuple[str, ...] = field(default=())

    @property
    def fingerprint(self) -> str:
        """Pipe-joined class, subject (test, frame or job), exception type and message."""
        subject = self.test or self.frame or self.job or "-"
        return "|".join((self.failure_class, subject, self.exception_type or "-", self.message or "-"))

    def to_dict(self) -> dict[str, Any]:
        """Return the fingerprint and its fields as a JSON-friendly dict."""
        return {
            "failure_class": self.failure_class,
            "fingerprint": self.fingerprint,
            "job": self.job,
            "test": self.test,
            "exception_type": self.exception_type,
            "message": self.message,
            "frame": self.frame,
            "exit_code": self.exit_code,
            "failed_tests": list(self.failed_tests),
        }


def _failure_class(summary: TestRunSummary, exit_code: int | None, text: str) -> str:
    if exit_code == 124 or "verification_timeout" in text:
        return "TIMEOUT"
    if exit_code == 127 or "command_not_runnable" in text:
        return "COMMAND_NOT_FOUND"
    if summary.failed:
        return "TEST_FAILURE"
    if summary.errors:
        return "TEST_ERROR"
    if summary.failures:
        return "TEST_FAILURE"
    return "COMMAND_FAILURE"


def fingerprint_failure(text: str, *, exit_code: int | None = None, job: str = "") -> FailureFingerprint:
    """Build a failure fingerprint from test-runner output and its exit code.

    Exit code 124 maps to TIMEOUT and 127 to COMMAND_NOT_FOUND. The message is normalized
    and the frame keeps only the file name.
    """
    summary = parse_test_output(text)
    lines = _lines(text)
    first = summary.failures[0] if summary.failures else None
    exc = first.exception_type if first else ""
    msg = first.message if first else ""
    frame = ""
    for line in lines:
        m = _PYTEST_FRAME.match(line.strip())
        if m:
            frame = frame or m.group("file").replace("\\", "/")
            exc = exc or m.group("exc")
            continue
        m = _TRACEBACK_FRAME.match(line)
        if m:
            frame = m.group("file").replace("\\", "/")
    if not exc:
        for line in reversed(lines):
            m = _EXCEPTION.match(line.strip())
            if m:
                exc, msg = m.group("exc"), msg or m.group("msg")
                break
    return FailureFingerprint(
        failure_class=_failure_class(summary, exit_code, text),
        job=job,
        test=first.nodeid if first else "",
        exception_type=exc,
        message=normalize_message(msg),
        frame=frame.rsplit("/", 1)[-1] if frame else "",
        exit_code=exit_code,
        failed_tests=tuple(sorted(summary.failed_ids)),
    )


def same_failure(a: FailureFingerprint, b: FailureFingerprint) -> bool | None:
    """Whether two failures are the same problem; ``None`` when there is too little to compare."""
    if a.failed_tests and b.failed_tests:
        return bool(set(a.failed_tests) & set(b.failed_tests))
    if a.exception_type and b.exception_type:
        if a.exception_type != b.exception_type:
            return False
        if a.frame and b.frame:
            return a.frame == b.frame
        return True
    return None

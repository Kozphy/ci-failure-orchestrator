"""Read-only diagnosis of one failed GitHub Actions run or one saved job log.

Nothing here writes to a repository or calls a model. Every finding names a job and
a step and, when the log is available, the log line its message came from.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from ..ci_audit.collect import (
    FAILED_CONCLUSIONS,
    classify_failure,
    failing_section,
    failure_message,
    job_record,
    log_lines,
    workflow_label,
)
from ..foundation.policy import RULE_FAILURE_CATEGORY, RULE_LOW_CONFIDENCE, PolicyConfig
from ..github_client import GitHubAPIError
from ..service.untrusted import clean_untrusted

SCHEMA = "actions-doctor.diagnosis.v1"
MAX_LOGS = 10
_RUN_HEADER = "##[group]Run "
_ERROR_MARK = "##[error]"
_AFFECTED_CONCLUSIONS = frozenset({"skipped", "cancelled"})
# ``uses:`` steps log "Run owner/action@ref"; that is not a command anyone can re-run locally.
_ACTION_REF_RE = re.compile(r"^(?:docker://\S+|[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[\w.-]+)$")

NEXT_STEPS = {
    "test_failure": "Reproduce the failing test with the command below and fix the code or the test it names.",
    "lint_failure": "Run the linter locally with the command below and fix the reported findings.",
    "type_failure": "Run the type checker locally with the command below and fix the reported errors.",
    "build_failure": "Reproduce the build locally; the first compiler or bundler error is usually the cause.",
    "dependency_failure": (
        "Check the package or version named in the error, then pin, update or add it in the dependency file."
    ),
    "network_failure": (
        "Often transient: re-run the job once. If it fails again, check the host or registry named in the error."
    ),
    "infrastructure_failure": (
        "Runner or service problem: check runner availability, disk, memory and job timeouts before changing code."
    ),
    "configuration_failure": "Check the workflow or tool configuration named in the error.",
    "flaky_failure": "Re-run once to confirm. If it passes, track the test as flaky instead of retrying silently.",
    "security_scan_failure": "Open the scanner's finding. Rotate any exposed secret before changing code.",
    "unknown": "No rule matched. Read the failing section of the log; nothing is inferred beyond it.",
}


class RunReader(Protocol):
    def get_run(self, repository: str, run_id: int) -> dict: ...

    def list_run_jobs(self, repository: str, run_id: int) -> list[dict]: ...

    def job_log(self, repository: str, job_id: int) -> str: ...


@dataclass(frozen=True)
class Finding:
    job: str
    step: str
    conclusion: str
    category: str
    confidence: str
    classified_by: str
    policy_category: str
    policy_confidence: float
    message: str
    evidence_line: int | None
    command: str
    started_at: str
    html_url: str
    log_available: bool
    rank_reason: str = ""


@dataclass(frozen=True)
class PolicyPreview:
    outcome: str
    rules: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Diagnosis:
    diagnosis_id: str
    source: str
    repository: str
    run_id: int | None
    run_attempt: int | None
    workflow: str
    head_sha: str
    run_url: str
    run_conclusion: str
    findings: tuple[Finding, ...]
    affected: tuple[tuple[str, str], ...]
    next_step: str
    verification: tuple[str, ...]
    policy: PolicyPreview | None
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, **asdict(self)}


def _evidence_line(log: str, message: str) -> int | None:
    """1-based line in the downloaded log that holds the message, preferring ``##[error]`` lines."""
    if not message:
        return None
    lines = log_lines(log)
    for wanted in (f"{_ERROR_MARK}{message}", message):
        for index, line in enumerate(lines):
            if wanted in line:
                return index + 1
    return None


def _confidence(category: str, classified_by: str, log: str, evidence_line: int | None) -> str:
    """Heuristic label: rules are not calibrated, so no percentage is reported."""
    if category == "unknown":
        return "low"
    specific = evidence_line is not None and log_lines(log)[evidence_line - 1].lstrip().startswith(_ERROR_MARK)
    return "high" if classified_by == "classifier" and specific else "medium"


def _finding(workflow: str, job: dict, log: str) -> Finding:
    entry = classify_failure(workflow, job, log)
    section = failing_section(log) if log else ""
    evidence_line = _evidence_line(log, failure_message(section)) if log else None
    header = next((line for line in section.splitlines() if line.startswith(_RUN_HEADER)), "")
    command = header[len(_RUN_HEADER) :].strip()
    if _ACTION_REF_RE.match(command):
        command = ""
    return Finding(
        job=entry["job"],
        step=entry["failed_step"],
        conclusion=str(job.get("conclusion") or "failure"),
        category=entry["category"],
        confidence=_confidence(entry["category"], entry["classified_by"], log, evidence_line),
        classified_by=entry["classified_by"],
        policy_category=entry["policy_category"],
        policy_confidence=float(entry["policy_confidence"]),
        message=entry["message"],
        evidence_line=evidence_line,
        command=clean_untrusted(command)[:500],
        started_at=str(job.get("started_at") or ""),
        html_url=str(job.get("html_url") or ""),
        log_available=bool(log),
    )


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def rank(findings: list[Finding]) -> list[Finding]:
    """Recognized causes first, then run order: the earliest failure usually explains the later ones."""
    in_order = sorted(findings, key=lambda f: (f.started_at, f.job))
    position = {id(f): i for i, f in enumerate(in_order)}
    ranked = sorted(findings, key=lambda f: (f.category == "unknown", position[id(f)]))
    result = []
    for finding in ranked:
        reason = (
            "only failed job"
            if len(findings) == 1
            else f"{_ordinal(position[id(finding)] + 1)} failed job in run order"
        )
        if finding.category == "unknown":
            reason += "; no rule matched the log"
        result.append(Finding(**{**asdict(finding), "rank_reason": reason}))
    return result


def policy_preview(top: Finding, config: PolicyConfig | None = None) -> PolicyPreview:
    """The category and confidence rules the policy engine applies before any patch exists."""
    cfg = config or PolicyConfig()
    rules: list[str] = []
    reasons: list[str] = []
    if top.policy_category in cfg.escalation_failure_categories:
        rules.append(RULE_FAILURE_CATEGORY)
        reasons.append(f"a passing patch does not show that a {top.policy_category} is fixed")
    if top.policy_confidence < cfg.min_classification_confidence:
        rules.append(RULE_LOW_CONFIDENCE)
        reasons.append(
            f"classification confidence {top.policy_confidence:.2f} is below {cfg.min_classification_confidence:.2f}"
        )
    return PolicyPreview("ESCALATE" if rules else "ELIGIBLE", tuple(rules), tuple(reasons))


def _verification(top: Finding, run_id: int | None) -> tuple[str, ...]:
    if top.command:
        return (top.command,)
    if run_id is not None:
        return (f"gh run rerun {run_id} --failed",)
    return ("re-run the failed job",)


def _assemble(
    *,
    diagnosis_id: str,
    source: str,
    repository: str,
    run: dict,
    attempt: int | None,
    findings: list[Finding],
    affected: list[tuple[str, str]],
    warnings: list[str],
) -> Diagnosis:
    ranked = rank(findings) if findings else []
    top = ranked[0] if ranked else None
    run_id = int(run["id"]) if run.get("id") is not None else None
    return Diagnosis(
        diagnosis_id=diagnosis_id,
        source=source,
        repository=repository,
        run_id=run_id,
        run_attempt=attempt,
        workflow=clean_untrusted(workflow_label(run)) if run else "",
        head_sha=str(run.get("head_sha") or ""),
        run_url=str(run.get("html_url") or ""),
        run_conclusion=str(run.get("conclusion") or ""),
        findings=tuple(ranked),
        affected=tuple(affected),
        next_step=NEXT_STEPS.get(top.category, NEXT_STEPS["unknown"]) if top else "",
        verification=_verification(top, run_id) if top else (),
        policy=policy_preview(top) if top else None,
        warnings=tuple(warnings),
    )


def diagnose_log(log: str, *, job: str = "job", step: str = "") -> Diagnosis:
    """Offline diagnosis of one saved job log; needs no token and no network."""
    record = {
        "id": None,
        "run_id": None,
        "run_attempt": 1,
        "name": clean_untrusted(job),
        "failed_step": clean_untrusted(step),
        "conclusion": "failure",
        "html_url": "",
    }
    digest = hashlib.sha256(log.encode("utf-8", errors="replace")).hexdigest()[:8]
    return _assemble(
        diagnosis_id=f"CID-log-{digest}",
        source="log",
        repository="",
        run={},
        attempt=None,
        findings=[_finding("", record, log)],
        affected=[],
        warnings=[] if log.strip() else ["the log is empty"],
    )


def diagnose_run(
    reader: RunReader,
    repository: str,
    run_id: int,
    *,
    attempt: int | None = None,
    job: str | None = None,
    max_logs: int = MAX_LOGS,
) -> Diagnosis:
    """Diagnose the failed jobs of one run attempt (default: the latest attempt)."""
    run = reader.get_run(repository, run_id)
    raw_jobs = reader.list_run_jobs(repository, run_id)
    attempts = [int(j.get("run_attempt") or 1) for j in raw_jobs] or [int(run.get("run_attempt") or 1)]
    chosen = attempt or max(attempts)
    jobs = [job_record(j) for j in raw_jobs if int(j.get("run_attempt") or 1) == chosen]
    if job:
        jobs = [j for j in jobs if j["name"] == job]

    warnings: list[str] = []
    failed = [j for j in jobs if j["conclusion"] in FAILED_CONCLUSIONS]
    if not jobs:
        warnings.append(f"no jobs found for attempt {chosen}" + (f" named {job!r}" if job else ""))
    elif not failed:
        warnings.append(f"no failed jobs in attempt {chosen} (run conclusion: {run.get('conclusion') or 'unknown'})")

    workflow = workflow_label(run)
    findings: list[Finding] = []
    for index, record in enumerate(sorted(failed, key=lambda j: str(j["started_at"] or ""))):
        log = ""
        if index < max_logs:
            try:
                log = reader.job_log(repository, int(record["id"]))
            except (GitHubAPIError, OSError) as exc:
                warnings.append(f"log for job {record['name']!r} unavailable: {clean_untrusted(str(exc))[:200]}")
        else:
            warnings.append(f"log for job {record['name']!r} not read (limit of {max_logs} logs)")
        findings.append(_finding(workflow, record, log))

    affected = [(j["name"], str(j["conclusion"])) for j in jobs if j["conclusion"] in _AFFECTED_CONCLUSIONS]
    created = str(run.get("created_at") or "")[:10].replace("-", "") or "undated"
    digest = hashlib.sha256(f"{repository}#{run_id}#{chosen}".encode()).hexdigest()[:8]
    return _assemble(
        diagnosis_id=f"CID-{created}-{digest}",
        source="github",
        repository=repository,
        run=run,
        attempt=chosen,
        findings=findings,
        affected=affected,
        warnings=warnings,
    )

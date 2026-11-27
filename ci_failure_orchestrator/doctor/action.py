"""GitHub Action entry point: diagnose one workflow run and publish the result to the job summary.

``action.yml`` passes every input through environment variables, so no input value is ever
interpolated into a shell script. Only read access to Actions is needed.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from ..github_client import GitHubActionsClient, GitHubAPIError
from ..service.untrusted import clean_untrusted, fenced, neutralize
from .cli import EXIT_INPUT, EXIT_OK, EXIT_USAGE
from .diagnose import Diagnosis, RunReader, diagnose_log, diagnose_run
from .reliability_report import build_reliability_report, render_reliability_markdown
from .render import render_text

_REPOSITORY_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_OUTPUT_FORMATS = frozenset({"json", "markdown", "both"})
MAX_LOG_BYTES = 2_000_000
EXIT_POLICY = 4


def _error(message: str) -> None:
    """One ``::error::`` annotation; the data is escaped so it cannot start a second command."""
    data = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error title=CI Doctor::{data}")


def _append(path: str | None, text: str) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)


def failure_class(diagnosis: Diagnosis) -> str:
    """Return the top finding's category, or ``"none"`` when there are no findings."""
    return diagnosis.findings[0].category if diagnosis.findings else "none"


def summary_markdown(diagnosis: Diagnosis, text: str) -> str:
    """Build the job-summary Markdown: a heading, the run link and the rendered text in a fence."""
    heading = failure_class(diagnosis) if diagnosis.findings else "nothing to diagnose"
    run = f"[Run {diagnosis.run_id}]({diagnosis.run_url})" if diagnosis.run_url else f"Run {diagnosis.run_id}"
    return f"## CI Doctor: {heading}\n\n{run}\n\n{fenced(text)}\n"


def _choice(value: str, allowed: frozenset[str], label: str) -> str | None:
    cleaned = value.strip().lower()
    if cleaned in allowed:
        return cleaned
    _error(f"{label} must be one of {', '.join(sorted(allowed))}")
    return None


def _enabled(value: str, *, default: bool) -> bool | None:
    cleaned = value.strip().lower()
    if cleaned == "":
        return default
    if cleaned in {"1", "true", "yes"}:
        return True
    if cleaned in {"0", "false", "no"}:
        return False
    _error(f"expected true or false, got {clean_untrusted(cleaned)[:40]!r}")
    return None


def _read_saved_log(path_str: str) -> str:
    if any(char in path_str for char in ("\n", "\r", "\x00")):
        raise ValueError("log path contains a control character")
    path = Path(path_str)
    if not path.is_file():
        raise ValueError("log path is not a file")
    if path.stat().st_size > MAX_LOG_BYTES:
        raise ValueError(f"log exceeds {MAX_LOG_BYTES} bytes")
    return path.read_text(encoding="utf-8", errors="replace")


def _publish(env: Mapping[str, str], diagnosis: Diagnosis, *, write_markdown: bool, report_path: str) -> Path:
    text = neutralize(render_text(diagnosis))
    sys.stdout.write(text)
    out_dir = Path(env.get("RUNNER_TEMP") or ".") / "ci-doctor"
    out_dir.mkdir(parents=True, exist_ok=True)
    diagnosis_file = out_dir / "diagnosis.json"
    payload = json.loads(json.dumps(diagnosis.to_dict()))
    diagnosis_file.write_text(json.dumps(_redact(payload), indent=2) + "\n", encoding="utf-8")
    report = build_reliability_report(diagnosis)
    markdown_path = ""
    if write_markdown:
        target = Path(report_path) if report_path else out_dir / "report.md"
        if report_path and not target.parent.is_dir():
            raise ValueError("report path directory does not exist")
        target.write_text(render_reliability_markdown(report), encoding="utf-8")
        markdown_path = str(target)
    policy = diagnosis.policy.outcome if diagnosis.policy is not None else "none"
    status = "diagnosed" if diagnosis.findings else "none"
    _append(env.get("GITHUB_STEP_SUMMARY"), summary_markdown(diagnosis, text))
    _append(
        env.get("GITHUB_OUTPUT"),
        "\n".join(
            [
                f"failure-class={failure_class(diagnosis)}",
                f"diagnosis-file={diagnosis_file}",
                f"diagnosis-status={status}",
                f"failure-category={failure_class(diagnosis)}",
                f"report-path={markdown_path}",
                f"policy-status={policy}",
                "",
            ]
        ),
    )
    return diagnosis_file


def _redact(value: object) -> object:
    if isinstance(value, str):
        return clean_untrusted(value)
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def main(environ: Mapping[str, str] | None = None, reader: RunReader | None = None) -> int:
    """Diagnose a saved log or one GitHub run. Writes summary, outputs, JSON, and optional Markdown.

    Returns ``EXIT_USAGE`` for invalid inputs, ``EXIT_INPUT`` when the log or run cannot be read,
    ``EXIT_POLICY`` when a policy preview says ESCALATE and failing on that is enabled, and
    ``EXIT_OK`` otherwise. Redaction cannot be turned off.
    """
    env = os.environ if environ is None else environ
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    output_format = _choice(env.get("CI_DOCTOR_OUTPUT_FORMAT", "both"), _OUTPUT_FORMATS, "output-format")
    if output_format is None:
        return EXIT_USAGE
    redact = _enabled(env.get("CI_DOCTOR_REDACT_SECRETS", ""), default=True)
    if redact is None:
        return EXIT_USAGE
    if redact is False:
        _error("redact-secrets cannot be disabled")
        return EXIT_USAGE
    fail_on_policy = _enabled(env.get("CI_DOCTOR_FAIL_ON_POLICY", ""), default=False)
    if fail_on_policy is None:
        return EXIT_USAGE
    report_path = env.get("CI_DOCTOR_REPORT_PATH", "").strip()
    if any(char in report_path for char in ("\n", "\r", "\x00")):
        _error("report-path contains a control character")
        return EXIT_USAGE

    log_path = env.get("CI_DOCTOR_LOG_PATH", "").strip()
    if log_path:
        try:
            diagnosis = diagnose_log(_read_saved_log(log_path), job="saved-log", step="")
        except (OSError, UnicodeError, ValueError) as exc:
            _error(clean_untrusted(str(exc))[:500])
            return EXIT_INPUT
    else:
        repository = env.get("CI_DOCTOR_REPOSITORY", "").strip()
        run_id = env.get("CI_DOCTOR_RUN_ID", "").strip()
        if not _REPOSITORY_RE.match(repository):
            _error(f"repository must be owner/name, got {clean_untrusted(repository)[:100]!r}")
            return EXIT_USAGE
        if not run_id.isdigit():
            _error("run-id is empty or not a number. Trigger this action on workflow_run or pass run-id.")
            return EXIT_USAGE
        if reader is None:
            reader = GitHubActionsClient(
                token=env.get("GITHUB_TOKEN") or None,
                api_url=env.get("GITHUB_API_URL") or "https://api.github.com",
            )
        try:
            diagnosis = diagnose_run(reader, repository, int(run_id))
        except (GitHubAPIError, ValueError, OSError) as exc:
            _error(f"cannot read run {run_id} of {repository}: {clean_untrusted(str(exc))[:500]}")
            return EXIT_INPUT

    try:
        _publish(env, diagnosis, write_markdown=output_format in {"markdown", "both"}, report_path=report_path)
    except (OSError, ValueError) as exc:
        _error(clean_untrusted(str(exc))[:500])
        return EXIT_INPUT
    if fail_on_policy and diagnosis.policy is not None and diagnosis.policy.outcome == "ESCALATE":
        return EXIT_POLICY
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

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
from .diagnose import Diagnosis, RunReader, diagnose_run
from .render import render_text

_REPOSITORY_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


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


def main(environ: Mapping[str, str] | None = None, reader: RunReader | None = None) -> int:
    """Diagnose the run named by ``CI_DOCTOR_*`` variables and write the summary, outputs and diagnosis.json.

    Returns ``EXIT_USAGE`` for an invalid repository or run id, ``EXIT_INPUT`` when the run cannot be
    read, and ``EXIT_OK`` otherwise.
    """
    env = os.environ if environ is None else environ
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

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

    text = neutralize(render_text(diagnosis))
    sys.stdout.write(text)

    out_dir = Path(env.get("RUNNER_TEMP") or ".") / "ci-doctor"
    out_dir.mkdir(parents=True, exist_ok=True)
    diagnosis_file = out_dir / "diagnosis.json"
    diagnosis_file.write_text(json.dumps(diagnosis.to_dict(), indent=2) + "\n", encoding="utf-8")

    _append(env.get("GITHUB_STEP_SUMMARY"), summary_markdown(diagnosis, text))
    _append(env.get("GITHUB_OUTPUT"), f"failure-class={failure_class(diagnosis)}\ndiagnosis-file={diagnosis_file}\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

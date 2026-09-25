"""Static checks: no workflow can auto-merge, and risky write paths are manual-only."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
MANUAL_ONLY = ("auto-merge-after-checks.yml", "self-heal.yml", "agent-issue-delivery.yml")
MERGE_PATTERN = re.compile(r"gh\s+pr\s+merge|enablePullRequestAutoMerge|merge_method")


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(doc: dict) -> set[str]:
    # PyYAML (YAML 1.1) parses the bare key `on` as boolean True.
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    return set(on or {})


def _job_disabled(job: dict) -> bool:
    condition = str(job.get("if", "")).replace(" ", "")
    return condition in {"false", "${{false}}", "False"}


def test_risky_workflows_are_manual_only():
    for name in MANUAL_ONLY:
        assert _triggers(_load(name)) == {"workflow_dispatch"}, name


def test_auto_merge_job_cannot_run_even_when_dispatched():
    jobs = _load("auto-merge-after-checks.yml")["jobs"]
    assert jobs
    assert all(_job_disabled(job) for job in jobs.values())


def test_no_enabled_workflow_merges_pull_requests():
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (doc.get("jobs") or {}).items():
            if _job_disabled(job):
                continue
            body = yaml.safe_dump(job)
            if MERGE_PATTERN.search(body):
                offenders.append(f"{path.name}:{job_name}")
    assert offenders == []


def test_no_workflow_triggers_on_pull_request_target():
    offenders = [
        path.name
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        if "pull_request_target" in _triggers(yaml.safe_load(path.read_text(encoding="utf-8")))
    ]
    assert offenders == []


def test_merge_detector_is_not_vacuous():
    job = {"steps": [{"run": 'gh pr merge "$PR" --squash'}]}
    assert MERGE_PATTERN.search(yaml.safe_dump(job))

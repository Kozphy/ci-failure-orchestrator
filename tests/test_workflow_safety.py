"""Static checks: no workflow can auto-merge, and no pull_request_target."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
MERGE_PATTERN = re.compile(r"gh\s+pr\s+merge|enablePullRequestAutoMerge|merge_method")


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


def test_risky_auto_merge_and_self_heal_workflows_are_gone():
    for name in (
        "auto-merge-after-checks.yml",
        "self-heal.yml",
        "agent-issue-delivery.yml",
    ):
        assert not (WORKFLOWS / name).exists(), name

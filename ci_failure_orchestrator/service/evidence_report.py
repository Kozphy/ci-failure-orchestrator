"""One customer-facing evidence report per repair attempt.

Every value is read from artifacts the run already stored (failure event, classification,
verification, remediation, policy, reviewer and apply records). Nothing is inferred beyond
them: a question the artifacts cannot answer is reported as unknown, and every piece of
missing evidence is listed as a remaining risk.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..foundation.durable import FileEvidenceStore
from ..foundation.models import utc_now
from .common import CI_VERIFICATION_NAME, FINAL_PATCH_NAME, FIX_DIR, METADATA_NAME, REMEDIATION_NAME, VERIFICATION_NAME

EVIDENCE_REPORT_SCHEMA = "ci-doctor.repair-evidence.v1"
EVIDENCE_REPORT_JSON = "evidence-report.json"
EVIDENCE_REPORT_MD = "evidence-report.md"

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

_MISSING_EVIDENCE_TEXT = {
    "original_failure_reproduced": "The original CI failure was not reproduced locally, or it failed differently.",
    "test_count_comparison": "Test counts before and after the patch could not be compared.",
    "affected_tests": "Tests mapped to the changed files were not run separately.",
    "regression_suite": "No regression suite ran, so tests outside the failing ones were not re-checked.",
    "coverage": "Coverage was not measured before and after the patch.",
    "lint": "No lint gate ran.",
    "typecheck": "No type-check gate ran.",
    "security": "No security gate ran.",
    "build": "No build gate ran.",
    "behavioral_invariants": "No behavioral invariant checks ran.",
    "real_ci_passed": "The real CI provider has not confirmed the applied change.",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _diff_path(header: str) -> str:
    path = header[4:].split("\t", 1)[0].strip()
    return path[2:] if path.startswith(("a/", "b/")) else path


def _diffstat(patch: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    old_path = ""
    old_left = new_left = 0
    for line in patch.splitlines():
        if old_left > 0 or new_left > 0:
            if line.startswith("-"):
                files[-1]["removed"] += 1
                old_left -= 1
            elif line.startswith("+"):
                files[-1]["added"] += 1
                new_left -= 1
            elif not line.startswith("\\"):
                old_left -= 1
                new_left -= 1
        elif line.startswith("--- "):
            old_path = _diff_path(line)
        elif line.startswith("+++ "):
            new_path = _diff_path(line)
            files.append({"path": old_path if new_path == "/dev/null" else new_path, "added": 0, "removed": 0})
        elif line.startswith("@@") and files and (hunk := _HUNK.match(line)):
            old_left = int(hunk.group(2) or 1)
            new_left = int(hunk.group(4) or 1)
    return files


def _pr_url(run_root: Path) -> str:
    try:
        lines = (run_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    url = ""
    for line in lines:
        try:
            meta = json.loads(line).get("metadata") or {}
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(meta, dict) and str(meta.get("url", "")).startswith("http"):
            url = str(meta["url"])
    return url


def _commands_run(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []

    def add(stage: str, record: Any) -> None:
        if isinstance(record, dict) and record.get("ran"):
            runs.append({"stage": stage, "command": record.get("command", ""), "returncode": record.get("returncode")})

    targeted = evidence.get("targeted_validation") or {}
    add("failing tests, before patch", targeted.get("before"))
    add("failing tests, after patch", targeted.get("after"))
    add("affected tests, after patch", (evidence.get("affected_tests") or {}).get("after"))
    for step in (evidence.get("regression") or {}).get("steps_after") or []:
        add("regression suite, after patch", step)
    for gate, steps in ((evidence.get("quality_baseline") or {}).get("steps_after") or {}).items():
        for step in steps or []:
            add(f"{gate} gate, after patch", step)
    for invariant in evidence.get("behavioral_invariants") or []:
        if isinstance(invariant, dict) and invariant.get("after_returncode") is not None:
            runs.append(
                {
                    "stage": f"invariant '{invariant.get('name')}', after patch",
                    "command": invariant.get("command", ""),
                    "returncode": invariant["after_returncode"],
                }
            )
    return runs


def build_repair_evidence(artifacts_root: Path, run_id: str) -> dict[str, Any]:
    """Assemble the evidence report for one run from its stored artifacts.

    Args:
        artifacts_root: Artifacts directory that holds ``runs/<run_id>/``.
        run_id: Foundation run ID of the repair attempt.

    Returns:
        A ``ci-doctor.repair-evidence.v1`` document. Sections the artifacts cannot answer hold
        None or empty lists rather than guesses.
    """
    run_root = FileEvidenceStore(Path(artifacts_root)).run_root(run_id)
    fix = run_root / FIX_DIR
    event = _read_json(run_root / "input" / "failure-event.json")
    classification = _read_json(run_root / "classification" / "classification.json")
    metadata = _read_json(fix / METADATA_NAME)
    remediation = _read_json(fix / REMEDIATION_NAME)
    verification = _read_json(fix / VERIFICATION_NAME)
    ci = _read_json(fix / CI_VERIFICATION_NAME)
    policy = _read_json(run_root / "policy" / "policy-decision.json")
    state = _read_json(run_root / "state.json")
    reviewer = _read_json(run_root / "reviewer" / "decision.json")
    applied = _read_json(run_root / "target" / "apply.json")
    metrics = _read_json(run_root / "metrics-summary.json")
    try:
        patch = (fix / FINAL_PATCH_NAME).read_text(encoding="utf-8")
    except OSError:
        patch = ""

    evidence = verification.get("evidence") or {}
    reproduction = evidence.get("reproduction") or {}
    regression = evidence.get("regression") or {}
    risk = evidence.get("diff_risk") or {}
    diffstat = _diffstat(patch)
    missing = [str(m) for m in remediation.get("missing_evidence") or []]
    merge_requirement = str(remediation.get("merge_requirement") or "")
    failure_class = str(classification.get("category") or "unknown")
    heuristic = "heuristic" in str(classification.get("uncertainty") or "")
    confidence = classification.get("confidence")

    remaining = [_MISSING_EVIDENCE_TEXT.get(m.split(":", 1)[0], f"Missing evidence: {m}") for m in missing]
    if heuristic:
        remaining.append("The failure class comes from heuristic pattern rules; its confidence is not calibrated.")
    remaining.extend(f"Diff risk: {reason}" for reason in risk.get("reasons") or [])

    return {
        "schema": EVIDENCE_REPORT_SCHEMA,
        "run_id": run_id,
        "generated_at": utc_now(),
        "data_source": str(event.get("source") or "unknown"),
        "what_broke": {
            "repository": event.get("repository") or "",
            "workflow": event.get("workflow") or "",
            "job": event.get("job") or "",
            "step": event.get("failed_step") or "",
            "commit": event.get("commit_sha") or "",
            "failure_message": event.get("message") or metadata.get("failure_message") or "",
            "failure_class": failure_class,
            "confidence": confidence,
            "confidence_kind": "heuristic" if heuristic else "unspecified",
            "classification_evidence": list(classification.get("evidence") or []),
        },
        "why_it_broke": {
            "root_cause_hypothesis": (
                f"{failure_class}: {event.get('message') or metadata.get('failure_message') or 'no failure message'}"
            ),
            "hypothesis_basis": "classification of the failing log line; not a verified root cause",
            "original_failure_reproduced": reproduction.get("original_failure_reproduced"),
            "reproduction_basis": reproduction.get("basis") or "",
            "failed_command": reproduction.get("failed_command") or "",
            "failed_test": reproduction.get("failed_test") or "",
        },
        "what_changed": {
            "proposal_source": metadata.get("proposal_source") or "",
            "base_commit": metadata.get("base_commit") or "",
            "patch_sha256": metadata.get("patch_sha256") or "",
            "files_changed": diffstat or [{"path": p, "added": None, "removed": None} for p in metadata.get("files_changed") or []],
            "lines_added": sum(f["added"] for f in diffstat),
            "lines_removed": sum(f["removed"] for f in diffstat),
        },
        "why_this_fix": {
            "selection": (
                f"candidate from attempt {remediation.get('repair_attempt')} of the retry budget; it was the one "
                "carried to verification and policy"
                if remediation.get("repair_attempted")
                else "no repair was attempted"
            ),
            "attempts": metrics.get("attempts"),
            "retries": metrics.get("retries"),
        },
        "tests": {
            "verify_commands": list(metadata.get("verify_commands") or []),
            "commands_run": _commands_run(evidence),
            "target_tests": list((evidence.get("targeted_validation") or {}).get("target_tests") or []),
            "targeted_validation": (remediation.get("checks") or {}).get("targeted_validation"),
            "regression_validation": (remediation.get("checks") or {}).get("regression_validation"),
            "tests_before": regression.get("tests_before"),
            "tests_after": regression.get("tests_after"),
            "new_failures": list(regression.get("new_failures") or []),
        },
        "safety_evidence": {
            "checks": remediation.get("checks") or {},
            "integrity_findings": list(evidence.get("integrity_findings") or []),
            "diff_risk": {
                "level": risk.get("risk_level") or remediation.get("risk_level"),
                "score": risk.get("risk_score"),
                "reasons": list(risk.get("reasons") or []),
            },
            "policy": {
                "outcome": policy.get("outcome"),
                "matched_rules": list(policy.get("matched_rules") or []),
                "reasons": list(policy.get("reasons") or []),
                "policy_version": policy.get("policy_version"),
            },
            "human_decision": {k: reviewer.get(k) for k in ("action", "reviewer_id", "timestamp", "comment") if k in reviewer}
            or None,
            "real_ci": {k: ci.get(k) for k in ("stage", "created_at") if k in ci} or None,
        },
        "remaining_risks": remaining,
        "outcome": {
            "remediation_state": remediation.get("state") or "NO_REPAIR_RECORDED",
            "verified": bool(remediation.get("verified")),
            "merge_requirement": merge_requirement,
            "human_approval_required": merge_requirement != "AUTOMATIC_VERIFICATION_ALLOWED",
            "workflow_status": state.get("workflow_status"),
            "applied": (
                {"branch": applied.get("branch"), "commit": applied.get("commit"), "pull_request": _pr_url(run_root)}
                if applied
                else None
            ),
            "merged": False,
        },
        "timestamps": {
            "failure_received_at": remediation.get("failure_received_at") or event.get("timestamp"),
            "decided_at": remediation.get("decided_at"),
        },
        "audit": {
            "run_directory": f"runs/{run_id}",
            "event_log": f"runs/{run_id}/events.jsonl",
            "verify_integrity": f"ci-orchestrator foundation-verify {run_id} --artifacts {Path(artifacts_root)}",
        },
    }


def _status_line(value: Any) -> str:
    return "unknown" if value is None or value == "" else str(value)


def render_repair_evidence_markdown(report: dict[str, Any]) -> str:
    """Render an evidence report as Markdown that answers the reviewer's questions in order."""
    broke, why, changed = report["what_broke"], report["why_it_broke"], report["what_changed"]
    tests, safety, outcome = report["tests"], report["safety_evidence"], report["outcome"]
    lines = [
        f"# Repair evidence: {report['run_id']}",
        "",
        (
            f"**Outcome:** `{outcome['remediation_state']}` | verified: {'yes' if outcome['verified'] else 'no'} | "
            f"before merging: `{_status_line(outcome['merge_requirement'])}` | nothing is merged automatically."
        ),
        f"Data source: `{report['data_source']}` | generated {report['generated_at']}",
        "",
        "## What broke?",
        (
            f"- {broke['workflow'] or 'workflow ?'} > {broke['job'] or 'job ?'} > {broke['step'] or 'step ?'}"
            f" at commit `{broke['commit'][:12] or '?'}`"
        ),
        f"- Failure: {broke['failure_message'] or 'no message recorded'}",
        f"- Class: `{broke['failure_class']}` (confidence {_status_line(broke['confidence'])}, {broke['confidence_kind']})",
        "",
        "## Why did it break?",
        f"- Hypothesis: {why['root_cause_hypothesis']}",
        f"- Basis: {why['hypothesis_basis']}",
        f"- Reproduced locally: {_status_line(why['original_failure_reproduced'])} ({why['reproduction_basis'] or 'no basis'})",
        "",
        "## What changed?",
        (
            f"- Source: {changed['proposal_source'] or 'unknown'} | base `{changed['base_commit'][:12] or '?'}` | "
            f"+{changed['lines_added']} -{changed['lines_removed']}"
        ),
        *[f"  - `{f['path']}` (+{_status_line(f['added'])} -{_status_line(f['removed'])})" for f in changed["files_changed"]],
        "",
        "## Why was this fix selected?",
        f"- {report['why_this_fix']['selection']}.",
        "",
        "## What tests were run?",
        *[f"- verify: `{c}`" for c in tests["verify_commands"]],
        *[f"- {r['stage']}: `{r['command']}` -> exit {r['returncode']}" for r in tests["commands_run"]],
        (
            f"- Targeted validation: {_status_line(tests['targeted_validation'])} | "
            f"regression validation: {_status_line(tests['regression_validation'])}"
        ),
        "",
        "## What evidence indicates the fix is safe?",
        *[f"- {name}: {_status_line(value)}" for name, value in sorted(safety["checks"].items())],
        f"- Integrity findings: {', '.join(str(f) for f in safety['integrity_findings']) or 'none'}",
        f"- Diff risk: {_status_line(safety['diff_risk']['level'])} (score {_status_line(safety['diff_risk']['score'])})",
        (
            f"- Policy: {_status_line(safety['policy']['outcome'])} | rules: "
            f"{', '.join(safety['policy']['matched_rules']) or 'none matched'}"
        ),
        f"- Human decision: {safety['human_decision'] or 'none recorded'}",
        "",
        "## What risks remain?",
        *([f"- {r}" for r in report["remaining_risks"]] or ["- None recorded."]),
        "",
        "## Audit",
        f"- Artifacts: `{report['audit']['run_directory']}` | events: `{report['audit']['event_log']}`",
        f"- Check integrity: `{report['audit']['verify_integrity']}`",
    ]
    if outcome["applied"]:
        applied = outcome["applied"]
        lines.append(f"- Applied to branch `{applied['branch']}` at `{str(applied['commit'])[:12]}`"
                     + (f" | {applied['pull_request']}" if applied["pull_request"] else ""))
    return "\n".join(lines) + "\n"


def write_repair_evidence(artifacts_root: Path, run_id: str) -> dict[str, Any]:
    """Build the evidence report and store it as JSON and Markdown in the run's ``fix-repo`` directory.

    Returns:
        The report that was written.

    Raises:
        PersistenceError: If either file cannot be written.
    """
    report = build_repair_evidence(artifacts_root, run_id)
    store = FileEvidenceStore(Path(artifacts_root))
    store.write_json(run_id, FIX_DIR, report, name=EVIDENCE_REPORT_JSON)
    store.write_text(run_id, FIX_DIR, render_repair_evidence_markdown(report), name=EVIDENCE_REPORT_MD)
    return report

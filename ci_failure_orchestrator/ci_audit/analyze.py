"""Metrics and ranked findings from a ci-audit export (pure, no I/O)."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime

from .collect import EXPORT_SCHEMA, FAILED_CONCLUSIONS

# GitHub-hosted minute multipliers; self-hosted runners are not billed.
OS_MULTIPLIER = {"linux": 1, "windows": 2, "macos": 10, "self-hosted": 0}
SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def _ts(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _minutes_between(start: object, end: object) -> float | None:
    a, b = _ts(start), _ts(end)
    if a is None or b is None or b < a:
        return None
    return (b - a).total_seconds() / 60


def percentile(values: list[float], pct: float) -> float:
    """Return the nearest-rank percentile of values rounded to one decimal, or 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return round(ordered[rank - 1], 1)


def _share(part: float, whole: float) -> float:
    return round(part / whole, 3) if whole else 0.0


def job_minutes(job: dict) -> tuple[int, int]:
    """(raw minutes rounded up per job, billed minutes with the OS multiplier)."""

    duration = _minutes_between(job.get("started_at"), job.get("completed_at"))
    raw = math.ceil(duration) if duration and duration > 0 else 0
    return raw, raw * OS_MULTIPLIER.get(job.get("runner_os", "linux"), 1)


def _wf(run: dict) -> str:
    return run.get("workflow") or run.get("name") or ""


def _flaky(completed: list[dict], jobs_by_run: dict[int, list[dict]]) -> list[dict]:
    found: dict[tuple, dict] = {}
    for run in completed:
        final = run.get("run_attempt") or 1
        if run.get("conclusion") == "success" and final > 1:
            earlier_failed = any(
                job["conclusion"] in FAILED_CONCLUSIONS and (job.get("run_attempt") or 1) < final
                for job in jobs_by_run.get(run["id"], [])
            )
            if earlier_failed:
                found.setdefault(
                    (run["workflow_id"], run["head_sha"]),
                    {"workflow": _wf(run), "head_sha": run["head_sha"], "kind": "rerun_passed", "url": run["html_url"]},
                )
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for run in completed:
        groups[(run["workflow_id"], run["head_sha"])].append(run)
    for key, group in groups.items():
        seen_failure = False
        for run in sorted(group, key=lambda r: str(r.get("created_at") or "")):
            if run.get("conclusion") in FAILED_CONCLUSIONS:
                seen_failure = True
            elif seen_failure and run.get("conclusion") == "success":
                found.setdefault(
                    key,
                    {"workflow": _wf(run), "head_sha": run["head_sha"], "kind": "fail_then_pass_same_commit", "url": run["html_url"]},
                )
                break
    return list(found.values())


def _duplicate_run_ids(completed: list[dict]) -> set[int]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for run in completed:
        groups[(run["workflow_id"], run["head_sha"])].append(run)
    duplicates: set[int] = set()
    for group in groups.values():
        if {"push", "pull_request"} <= {run.get("event") for run in group}:
            ordered = sorted(group, key=lambda r: str(r.get("created_at") or ""))
            duplicates.update(run["id"] for run in ordered[1:])
    return duplicates


def _finding(fid: str, severity: str, title: str, evidence: str, recommendation: str, effort: str, impact: int = 0) -> dict:
    return {
        "id": fid,
        "severity": severity,
        "title": title,
        "evidence": evidence,
        "recommendation": recommendation,
        "effort": effort,
        "monthly_minutes_at_stake": impact,
    }


def _findings(a: dict) -> list[dict]:
    t, waste, os_minutes = a["totals"], a["waste"], a["os_minutes"]
    scale = a["monthly_scale"]
    billed = t["billed_minutes"] or 0
    out: list[dict] = []

    costly = os_minutes.get("windows", 0) + os_minutes.get("macos", 0)
    costly_share = _share(costly, billed)
    if costly_share >= 0.25:
        out.append(_finding(
            "F-OS", "High" if costly_share >= 0.4 else "Medium",
            f"Windows/macOS jobs use {costly_share:.0%} of billed minutes",
            f"{costly} of {billed} billed minutes (Windows bills 2x, macOS 10x).",
            "Run these jobs on push to protected branches, a weekly schedule, or a PR label; keep Linux as the per-PR gate.",
            "Low", round(costly * scale * 0.6),
        ))
    dup_share = _share(waste["duplicate_minutes"], billed)
    if dup_share >= 0.05:
        out.append(_finding(
            "F-DUP", "High" if dup_share >= 0.15 else "Medium",
            f"push and pull_request both run on the same commits ({dup_share:.0%} of minutes)",
            f"{waste['duplicate_runs']} duplicate runs, {waste['duplicate_minutes']} billed minutes.",
            "Limit push triggers to protected branches so PR branches build once via pull_request.",
            "Low", round(waste["duplicate_minutes"] * scale),
        ))
    if t["rerun_rate"] >= 0.05 or t["flaky_groups"] >= 3:
        out.append(_finding(
            "F-FLAKY", "High" if t["rerun_rate"] >= 0.15 or t["flaky_groups"] >= 10 else "Medium",
            f"{t['rerun_rate']:.0%} of runs were rerun; {t['flaky_groups']} commits failed then passed unchanged",
            f"{waste['rerun_minutes']} billed minutes spent on earlier attempts.",
            "Identify the flaky tests behind these commits, quarantine them in a non-blocking job, and fix or delete them.",
            "Medium", round(waste["rerun_minutes"] * scale),
        ))
    if t["failure_rate"] >= 0.2 and t["failed"] >= 5:
        out.append(_finding(
            "F-FAIL", "High" if t["failure_rate"] >= 0.35 else "Medium",
            f"{t['failure_rate']:.0%} of completed runs failed",
            f"{t['failed']} failed of {t['failed'] + t['succeeded']} decided runs.",
            "Work the top failing jobs and failure categories below first; most failures usually come from a few jobs.",
            "Medium", round(waste["failed_minutes"] * scale),
        ))
    top = a["top_failing_jobs"][:1]
    if top and top[0]["share"] >= 0.4 and top[0]["count"] >= 5:
        out.append(_finding(
            "F-TOPJOB", "Medium",
            f"One job causes {top[0]['share']:.0%} of failed jobs: {top[0]['workflow']} / {top[0]['job']}",
            f"{top[0]['count']} failures; example {top[0]['example_url']}",
            "Make this job the first fix target: read its failure category and failing step in the evidence section.",
            "Medium",
        ))
    read, unread = a["logs_read"], a["logs_read_unknown"]
    if unread >= 5 and _share(unread, read) >= 0.3:
        out.append(_finding(
            "F-SIGNAL", "Low",
            f"{_share(unread, read):.0%} of failures match no known failure category",
            f"{unread} of {read} downloaded failure logs matched no known error pattern.",
            "Read the uncategorized examples in section 3 by hand; where the error line is vague, make the step print one "
            "explicit error (pytest -rA summaries, set -e, a clear message before exit).",
            "Low",
        ))
    slow = [w for w in a["workflows"] if w["p90_minutes"] >= 20]
    if slow:
        names = ", ".join(f"{w['name']} (p90 {w['p90_minutes']} min)" for w in slow[:3])
        out.append(_finding(
            "F-SLOW", "Medium", "Slow workflows delay feedback on every change",
            names,
            "Add dependency caching, split long test jobs, and skip work for docs-only changes with path filters.",
            "Medium",
        ))
    queued = [w for w in a["workflows"] if w["queue_p50_minutes"] >= 2]
    if queued:
        out.append(_finding(
            "F-QUEUE", "Low", "Runs wait in the queue before starting",
            ", ".join(f"{w['name']} (median {w['queue_p50_minutes']} min)" for w in queued[:3]),
            "Check concurrency limits and runner capacity; cancel superseded runs with concurrency groups.",
            "Low",
        ))
    cancel_share = _share(waste["cancelled_minutes"], billed)
    if cancel_share >= 0.1:
        out.append(_finding(
            "F-CANCEL", "Low", f"Cancelled jobs used {cancel_share:.0%} of minutes",
            f"{waste['cancelled_minutes']} billed minutes on jobs that were cancelled.",
            "Cancel earlier, e.g. concurrency groups with cancel-in-progress on PR workflows, or fail fast on cheap checks first.",
            "Low", round(waste["cancelled_minutes"] * scale),
        ))
    return sorted(out, key=lambda f: (SEVERITY_ORDER[f["severity"]], -f["monthly_minutes_at_stake"]))


def analyze_export(export: dict) -> dict:
    """Compute totals, minute waste, per-workflow metrics and ranked findings from a ci-audit export.

    Raises:
        ValueError: When the export's schema is not ``EXPORT_SCHEMA``.
    """
    if export.get("schema") != EXPORT_SCHEMA:
        raise ValueError(f"unsupported export schema: {export.get('schema')!r}")
    runs, jobs, failures = export["runs"], export["jobs"], export["failures"]
    scale = 30 / export["window_days"]

    completed = [run for run in runs if run.get("status") == "completed"]
    run_by_id = {run["id"]: run for run in completed}
    jobs_by_run: dict[int, list[dict]] = defaultdict(list)
    for job in jobs:
        jobs_by_run[job["run_id"]].append(job)

    failed = sum(1 for run in completed if run.get("conclusion") in FAILED_CONCLUSIONS)
    succeeded = sum(1 for run in completed if run.get("conclusion") == "success")
    cancelled = sum(1 for run in completed if run.get("conclusion") == "cancelled")
    reruns = sum(1 for run in completed if (run.get("run_attempt") or 1) > 1)
    flaky = _flaky(completed, jobs_by_run)
    duplicates = _duplicate_run_ids(completed)

    os_minutes: Counter = Counter()
    waste = Counter()
    raw_total = billed_total = 0
    per_workflow_minutes: Counter = Counter()
    job_durations: dict[tuple, list[float]] = defaultdict(list)
    for job in jobs:
        run = run_by_id.get(job["run_id"])
        if run is None:
            continue
        raw, billed = job_minutes(job)
        raw_total += raw
        billed_total += billed
        os_minutes[job["runner_os"]] += billed
        per_workflow_minutes[_wf(run)] += billed
        if raw:
            job_durations[(_wf(run), job["name"])].append(float(raw))
        if run["id"] in duplicates:
            waste["duplicate_minutes"] += billed
        elif (job.get("run_attempt") or 1) < (run.get("run_attempt") or 1):
            waste["rerun_minutes"] += billed
        elif job["conclusion"] == "cancelled":
            waste["cancelled_minutes"] += billed
        if job["conclusion"] in FAILED_CONCLUSIONS:
            waste["failed_minutes"] += billed
    waste_total = waste["duplicate_minutes"] + waste["rerun_minutes"] + waste["cancelled_minutes"]

    workflows = []
    for name in sorted({_wf(run) for run in completed}):
        group = [run for run in completed if _wf(run) == name]
        durations = [d for run in group if (d := _minutes_between(run.get("run_started_at"), run.get("updated_at"))) is not None]
        queues = [q for run in group if (q := _minutes_between(run.get("created_at"), run.get("run_started_at"))) is not None]
        decided = [run for run in group if run.get("conclusion") in FAILED_CONCLUSIONS or run.get("conclusion") == "success"]
        wf_failed = sum(1 for run in decided if run.get("conclusion") in FAILED_CONCLUSIONS)
        workflows.append({
            "name": name,
            "runs": len(group),
            "failure_rate": _share(wf_failed, len(decided)),
            "reruns": sum(1 for run in group if (run.get("run_attempt") or 1) > 1),
            "p50_minutes": percentile(durations, 50),
            "p90_minutes": percentile(durations, 90),
            "queue_p50_minutes": percentile(queues, 50),
            "billed_minutes": per_workflow_minutes[name],
            "share": _share(per_workflow_minutes[name], billed_total),
        })
    workflows.sort(key=lambda w: -w["billed_minutes"])

    categories = Counter(f["category"] for f in failures)
    taxonomy = [
        {
            "category": category,
            "count": count,
            "share": _share(count, len(failures)),
            "example_url": next(f["html_url"] for f in failures if f["category"] == category),
            "example_message": next(f["message"] for f in failures if f["category"] == category),
        }
        for category, count in categories.most_common()
    ]
    job_counts = Counter((f["workflow"], f["job"]) for f in failures)
    top_failing_jobs = [
        {
            "workflow": workflow,
            "job": job,
            "count": count,
            "share": _share(count, len(failures)),
            "example_url": next(f["html_url"] for f in failures if (f["workflow"], f["job"]) == (workflow, job)),
        }
        for (workflow, job), count in job_counts.most_common(10)
    ]
    step_counts = Counter((f["workflow"], f["job"], f["failed_step"] or "unknown") for f in failures)
    failing_steps = [
        {"workflow": w, "job": j, "step": s, "count": c} for (w, j, s), c in step_counts.most_common(10)
    ]
    slowest_jobs = sorted(
        (
            {"workflow": w, "job": j, "runs": len(d), "p50_minutes": percentile(d, 50), "p90_minutes": percentile(d, 90)}
            for (w, j), d in job_durations.items()
        ),
        key=lambda row: -row["p50_minutes"],
    )[:10]

    decided_total = failed + succeeded
    analysis = {
        "repository": export["repository"],
        "private": export.get("private"),
        "since": export["since"],
        "collected_at": export["collected_at"],
        "window_days": export["window_days"],
        "monthly_scale": scale,
        "totals": {
            "runs": len(runs),
            "completed": len(completed),
            "in_progress": len(runs) - len(completed),
            "succeeded": succeeded,
            "failed": failed,
            "cancelled": cancelled,
            "failure_rate": _share(failed, decided_total),
            "rerun_runs": reruns,
            "rerun_rate": _share(reruns, len(completed)),
            "flaky_groups": len(flaky),
            "failed_jobs": len(failures),
            "raw_minutes": raw_total,
            "billed_minutes": billed_total,
            "monthly_billed_minutes": round(billed_total * scale),
        },
        "os_minutes": dict(os_minutes),
        "waste": {
            "duplicate_runs": len(duplicates),
            "duplicate_minutes": waste["duplicate_minutes"],
            "rerun_minutes": waste["rerun_minutes"],
            "cancelled_minutes": waste["cancelled_minutes"],
            "failed_minutes": waste["failed_minutes"],
            "total_minutes": waste_total,
            "share": _share(waste_total, billed_total),
            "monthly_minutes": round(waste_total * scale),
        },
        "workflows": workflows,
        "taxonomy": taxonomy,
        "top_failing_jobs": top_failing_jobs,
        "failing_steps": failing_steps,
        "slowest_jobs": slowest_jobs,
        "flaky": flaky[:20],
        "logs_missing": sum(1 for f in failures if not f.get("log_available")),
        "logs_read": sum(1 for f in failures if f.get("log_available")),
        "logs_read_unknown": sum(1 for f in failures if f.get("log_available") and f["category"] == "unknown"),
        "warnings": list(export.get("warnings") or []),
        "limits": dict(export.get("limits") or {}),
    }
    analysis["findings"] = _findings(analysis)
    return analysis

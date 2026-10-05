"""Render a ci-audit analysis as a Markdown report."""

from __future__ import annotations

EDIT = "> _Reviewer: confirm or edit this section before delivery._"


def _pct(value: float) -> str:
    return f"{value:.0%}"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    if not rows:
        return ["_None found in this window._", ""]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return [*lines, ""]


def _link(url: object, text: str = "run") -> str:
    return f"[{text}]({url})" if url else "-"


def render_report(a: dict) -> str:
    """Render an analysis produced by ``analyze_export`` as a Markdown report."""
    t, waste, findings = a["totals"], a["waste"], a["findings"]
    billing = (
        "Public repository: GitHub-hosted minutes are free, so minute figures measure runner time and feedback delay, not spend."
        if a.get("private") is False
        else "Minute figures estimate billed GitHub-hosted minutes from job durations (Linux 1x, Windows 2x, macOS 10x)."
    )
    lines: list[str] = [
        f"# GitHub CI Reliability Audit: `{a['repository']}`",
        "",
        (
            f"Window: {a['since']} to {a['collected_at'][:10]} ({a['window_days']} days) · "
            f"{t['completed']} completed runs ({t['succeeded'] + t['failed']} passed or failed, the rest skipped or cancelled) · "
            f"{t['failed_jobs']} failed jobs"
        ),
        "",
        "## 1. Executive summary",
        "",
        f"- **Failure rate:** {_pct(t['failure_rate'])} of decided runs failed ({t['failed']} of {t['failed'] + t['succeeded']}).",
        f"- **Rerun rate:** {_pct(t['rerun_rate'])} of runs were rerun; {t['flaky_groups']} commits failed and then passed with no code change.",
        (
            f"- **Estimated waste:** {waste['total_minutes']} of {t['billed_minutes']} minutes ({_pct(waste['share'])}) went to duplicate runs, "
            f"superseded attempts and cancelled jobs, about **{waste['monthly_minutes']} minutes/month**."
        ),
        f"- **Estimated usage:** about {t['monthly_billed_minutes']} minutes/month at the current rate.",
        "",
    ]
    if findings:
        lines.append(f"**Fix first:** {findings[0]['title']}. {findings[0]['recommendation']}")
        lines.append("")
    lines += [EDIT, "", "## 2. Repository and workflow inventory", ""]
    lines += _table(
        ["Workflow", "Runs", "Failure rate", "Reruns", "p50 min", "p90 min", "Queue p50", "Minutes", "Share"],
        [
            [w["name"], w["runs"], _pct(w["failure_rate"]), w["reruns"], w["p50_minutes"], w["p90_minutes"],
             w["queue_p50_minutes"], w["billed_minutes"], _pct(w["share"])]
            for w in a["workflows"]
        ],
    )
    lines += ["Minutes by runner OS: " + (", ".join(f"{k} {v}" for k, v in sorted(a["os_minutes"].items())) or "none"), ""]

    lines += ["## 3. Failure taxonomy", ""]
    lines += _table(
        ["Category", "Failed jobs", "Share", "Example"],
        [[r["category"], r["count"], _pct(r["share"]), _link(r["example_url"], r["example_message"][:80] or "run")] for r in a["taxonomy"]],
    )
    lines += ["Top failing jobs:", ""]
    lines += _table(
        ["Workflow", "Job", "Failures", "Share", "Example"],
        [[r["workflow"], r["job"], r["count"], _pct(r["share"]), _link(r["example_url"])] for r in a["top_failing_jobs"]],
    )

    lines += ["## 4. CI bottlenecks", "", "Slowest jobs (minutes, rounded up per job):", ""]
    lines += _table(
        ["Workflow", "Job", "Runs", "p50", "p90"],
        [[r["workflow"], r["job"], r["runs"], r["p50_minutes"], r["p90_minutes"]] for r in a["slowest_jobs"]],
    )

    lines += ["## 5. Flaky-test indicators", "",
              "Commits where a workflow failed and then passed without a code change. These are indicators, not proof.", ""]
    lines += _table(
        ["Workflow", "Commit", "Signal", "Evidence"],
        [[r["workflow"], str(r["head_sha"])[:7], r["kind"], _link(r["url"])] for r in a["flaky"]],
    )

    lines += [
        "## 6. Retry analysis", "",
        f"- Runs with more than one attempt: {t['rerun_runs']} ({_pct(t['rerun_rate'])}).",
        f"- Minutes spent on superseded attempts: {waste['rerun_minutes']}.",
        f"- Reruns that turned red into green: {sum(1 for r in a['flaky'] if r['kind'] == 'rerun_passed')}.",
        "",
        "## 7. Cost and runtime waste", "",
        billing, "",
    ]
    lines += _table(
        ["Source", "Minutes in window", "Per month (est.)"],
        [
            ["Duplicate push + pull_request runs", waste["duplicate_minutes"], round(waste["duplicate_minutes"] * a["monthly_scale"])],
            ["Superseded attempts (reruns)", waste["rerun_minutes"], round(waste["rerun_minutes"] * a["monthly_scale"])],
            ["Cancelled jobs", waste["cancelled_minutes"], round(waste["cancelled_minutes"] * a["monthly_scale"])],
            ["**Total waste**", waste["total_minutes"], waste["monthly_minutes"]],
            ["Failed jobs (not counted as waste)", waste["failed_minutes"], round(waste["failed_minutes"] * a["monthly_scale"])],
        ],
    )

    lines += ["## 8. Risk ranking", ""]
    lines += _table(
        ["ID", "Severity", "Finding", "Effort", "Minutes/month at stake"],
        [[f["id"], f["severity"], f["title"], f["effort"], f["monthly_minutes_at_stake"] or "-"] for f in findings],
    )

    lines += ["## 9. Evidence", ""]
    lines += [f"- **{f['id']}:** {f['evidence']}" for f in findings] or ["_No findings._"]
    lines += ["", "Most frequent failing steps:", ""]
    lines += _table(
        ["Workflow", "Job", "Step", "Failures"],
        [[r["workflow"], r["job"], r["step"], r["count"]] for r in a["failing_steps"]],
    )

    lines += ["## 10. Recommended fixes", ""]
    lines += [f"{i}. **{f['title']}** ({f['severity']}, effort {f['effort']}): {f['recommendation']}" for i, f in enumerate(findings[:5], 1)]
    lines += ["", EDIT, "", "## 11. Quick wins", ""]
    quick = [f for f in findings if f["effort"] == "Low"]
    lines += [f"- {f['recommendation']}" for f in quick] or ["_No low-effort changes identified from run data._"]
    lines += [
        "", "## 12. 30-day roadmap", "",
        "- **Week 1:** apply the quick wins above.",
        f"- **Week 2:** fix the top finding{(' (' + findings[0]['id'] + ')') if findings else ''} and its failing job.",
        (
            "- **Week 3:** quarantine or fix the flaky tests behind section 5."
            if a["flaky"]
            else f"- **Week 3:** fix the next finding{(' (' + findings[1]['id'] + ')') if len(findings) > 1 else ''} and add a failure-rate check to the weekly review."
        ),
        "- **Week 4:** re-run this audit over the same window length and compare.",
        "", EDIT, "",
        "## 13. Method and limitations", "",
        "- Data: GitHub Actions REST API, read-only. No code, secrets or full logs are stored; failure messages are one scrubbed line.",
        "- Minutes are estimates from job start/end times rounded up per job, not billing data. Larger runners bill differently.",
        "- Failure categories come from a regex classifier and are not calibrated; spot-check them before acting.",
        "- Flaky signals are indicators: a commit that failed then passed may also reflect external outages.",
    ]
    if t["completed"] < 30:
        lines.append(f"- Small sample: {t['completed']} completed runs. Treat rates as rough.")
    if a["limits"].get("runs_truncated"):
        lines.append(f"- Run list capped at {a['limits'].get('max_runs')} runs; older runs in the window were not analyzed.")
    if a["logs_missing"]:
        lines.append(f"- {a['logs_missing']} failed jobs were classified from job and step names only (log not fetched).")
    lines += [f"- Collection warning: {w}" for w in a["warnings"][:5]]
    return "\n".join(lines) + "\n"

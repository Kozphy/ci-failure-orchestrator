"""Plain-text rendering of a diagnosis for terminals and CI logs."""

from __future__ import annotations

import textwrap

from .diagnose import Diagnosis, Finding

_LABEL_WIDTH = 17
_WIDTH = 100
_FILE_RULES_NOTE = (
    "File rules (forbidden paths, CI workflows, dependency and auth files, scope) apply once a patch exists."
)


def _row(label: str, value: str, *, wrap: bool = True) -> list[str]:
    """Label column plus value; commands pass ``wrap=False`` so they stay copy-pasteable."""
    indent = " " * _LABEL_WIDTH
    lines: list[str] = []
    for i, part in enumerate(value.splitlines() or [""]):
        wrapped = (textwrap.wrap(part, _WIDTH - _LABEL_WIDTH) if wrap else [part]) or [""]
        for j, text in enumerate(wrapped):
            prefix = label.ljust(_LABEL_WIDTH) if i == 0 and j == 0 else indent
            lines.append(f"{prefix}{text}".rstrip())
    return lines


def _where(finding: Finding) -> str:
    parts = [f'job "{finding.job}"']
    if finding.step:
        parts.append(f'step "{finding.step}"')
    if finding.evidence_line is not None:
        parts.append(f"log line {finding.evidence_line}")
    elif not finding.log_available:
        parts.append("log not available")
    return " > ".join(parts)


def _title(d: Diagnosis) -> str:
    if d.source == "log":
        return "CI Doctor | analyze | saved log"
    attempt = f" (attempt {d.run_attempt})" if d.run_attempt else ""
    return f"CI Doctor | analyze | {d.repository} | run {d.run_id}{attempt}"


def _recommended(d: Diagnosis, top: Finding) -> list[str]:
    if top.category == "security_scan_failure":
        return _row(
            "Recommended",
            "A maintainer reviews the scanner's finding. CI Doctor does not propose code changes for security findings.",
        )
    verify = d.verification[0] if top.command else "<command that reproduces the failure>"
    command = f'ci-orchestrator fix-repo --repo-path . --verify "{verify}" --patch-file fix.diff'
    if d.policy is not None and d.policy.outcome == "ESCALATE":
        advice = (
            "A maintainer reviews this failure. A candidate fix can still be verified in a disposable "
            "worktree, and policy will route it to approval:"
        )
    else:
        advice = "Verify a candidate fix in a disposable worktree:"
    return _row("Recommended", advice) + _row("", command, wrap=False)


def render_text(d: Diagnosis) -> str:
    lines = [_title(d)]
    if d.source == "github":
        lines.append(" | ".join(part for part in (d.workflow, f"commit {d.head_sha[:7]}", d.run_url) if part))
    lines.append("")

    if not d.findings:
        lines.append("Nothing to diagnose.")
        lines.extend(f"Note: {warning}" for warning in d.warnings)
        return "\n".join(lines) + "\n"

    top = d.findings[0]
    category = f"{top.category}    confidence: {top.confidence} (heuristic)"
    if top.policy_category != top.category:
        category += f"\npolicy gate sees: {top.policy_category}"
    lines += _row("Failure class", category)
    lines += _row("Evidence", f"{_where(top)}\n{top.message}")
    if top.command:
        lines += _row("Failing command", top.command, wrap=False)
    affected = [f"{f.job} ({f.conclusion})" for f in d.findings] + [f"{job} ({c})" for job, c in d.affected]
    lines += _row("Affected jobs", ", ".join(affected))

    if len(d.findings) > 1:
        lines += ["", "Root-cause candidates"]
        for i, f in enumerate(d.findings, start=1):
            where = f"{f.job} > {f.step}" if f.step else f.job
            lines.append(f"  {i}. {where}   {f.category}   {f.rank_reason}")
    lines.append("")

    lines += _row("Next step", d.next_step)
    lines += _row("Verification", "re-run: " + "\n".join(d.verification), wrap=False)
    if d.policy is not None:
        if d.policy.outcome == "ESCALATE":
            policy = "ESCALATE before any repair\n" + "\n".join(
                f"{rule}: {reason}" for rule, reason in zip(d.policy.rules, d.policy.reasons)
            )
        else:
            policy = "No category or confidence rule blocks an automated repair."
        if top.policy_category != top.category:
            policy += f"\nThe engine decides on its own category, {top.policy_category}, not {top.category}."
        lines += _row("Policy preview", f"{policy}\n{_FILE_RULES_NOTE}")
    lines += _recommended(d, top)
    lines.append("")
    lines += _row("Diagnosis ID", d.diagnosis_id)
    lines.extend(f"Note: {warning}" for warning in d.warnings)
    return "\n".join(lines) + "\n"

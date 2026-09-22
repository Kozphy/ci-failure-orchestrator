"""Phase 9 — Human Escalation evidence packages.

Triggered only on PolicyOutcome.ESCALATE.
Does not decide for the human, notify channels, or apply patches.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .models import (
    EvaluationResult,
    FailureClassification,
    FailureEvent,
    RepairProposal,
    new_id,
    utc_now,
)
from .policy import (
    RULE_AUTH_CHANGE,
    RULE_BROAD_SCOPE,
    RULE_CI_WORKFLOW,
    RULE_DEFAULT_ESCALATION,
    RULE_DEPENDENCY_CHANGE,
    RULE_ENGINE_FAILURE,
    RULE_HIGH_RETRY_COUNT,
    RULE_RESTRICTED_TOOL,
    RULE_SECURITY_SENSITIVE,
    ChangeScope,
    FileCategory,
    GovernanceRiskLevel,
    PolicyDecision,
    PolicyOutcome,
    classify_file,
    classify_scope,
)
from .retry import AttemptRecord
from .sanitization import sanitize_text

ESCALATION_SCHEMA = "foundation.escalation.v1"


class EscalationReasonCode(str, Enum):
    SECURITY_SENSITIVE_CHANGE = "SECURITY_SENSITIVE_CHANGE"
    AUTHORIZATION_CHANGE = "AUTHORIZATION_CHANGE"
    CI_WORKFLOW_CHANGE = "CI_WORKFLOW_CHANGE"
    DEPENDENCY_CHANGE = "DEPENDENCY_CHANGE"
    INFRASTRUCTURE_CHANGE = "INFRASTRUCTURE_CHANGE"
    PRODUCTION_CONFIG_CHANGE = "PRODUCTION_CONFIG_CHANGE"
    DATABASE_MIGRATION = "DATABASE_MIGRATION"
    BROAD_CHANGE_SCOPE = "BROAD_CHANGE_SCOPE"
    POLICY_UNCERTAINTY = "POLICY_UNCERTAINTY"
    UNKNOWN_CHANGE_CATEGORY = "UNKNOWN_CHANGE_CATEGORY"
    MAX_RETRY_SUCCESS_WITH_UNCERTAINTY = "MAX_RETRY_SUCCESS_WITH_UNCERTAINTY"
    RESTRICTED_TOOL_USED = "RESTRICTED_TOOL_USED"
    OTHER_POLICY_ESCALATION = "OTHER_POLICY_ESCALATION"


class ReviewerAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    DEFER = "DEFER"


class EvidenceCompletenessStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    ref: str


@dataclass(frozen=True)
class EvidenceCompleteness:
    status: EvidenceCompletenessStatus
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewerDecision:
    """Human reviewer decision recorded after policy ESCALATE / AWAITING_HUMAN.

    Applied via ``persistence.apply_reviewer_decision``. Does not mutate the
    primary workspace even when action is APPROVE.
    """

    escalation_id: str
    action: ReviewerAction
    reviewer_id: str = ""
    comment: str = ""
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalation_id": self.escalation_id,
            "action": self.action.value,
            "reviewer_id": self.reviewer_id,
            "comment": self.comment,
            "timestamp": self.timestamp,
            "primary_workspace_mutated": False,
        }


@dataclass(frozen=True)
class HumanEscalation:
    escalation_id: str
    run_id: str
    reason_codes: tuple[EscalationReasonCode, ...]
    summary: str
    policy_outcome: str
    matched_policy_rules: tuple[str, ...]
    risk_level: GovernanceRiskLevel
    failure_summary: str
    proposed_change_summary: str
    affected_files: tuple[str, ...]
    file_categories: tuple[str, ...]
    change_scope: ChangeScope
    evaluation_summary: str
    attempt_summary: str
    policy_summary: str
    unresolved_questions: tuple[str, ...]
    reviewer_checklist: tuple[str, ...]
    reviewer_actions: tuple[ReviewerAction, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    evidence_completeness: EvidenceCompleteness
    patch_stats: dict[str, int] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    schema_version: str = ESCALATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reason_codes"] = [c.value for c in self.reason_codes]
        data["risk_level"] = self.risk_level.value
        data["change_scope"] = self.change_scope.value
        data["reviewer_actions"] = [a.value for a in self.reviewer_actions]
        data["evidence_completeness"] = {
            "status": self.evidence_completeness.status.value,
            "missing": list(self.evidence_completeness.missing),
        }
        data["evidence_refs"] = [{"kind": e.kind, "ref": e.ref} for e in self.evidence_refs]
        return data


_RULE_TO_REASON: dict[str, EscalationReasonCode] = {
    RULE_AUTH_CHANGE: EscalationReasonCode.AUTHORIZATION_CHANGE,
    RULE_SECURITY_SENSITIVE: EscalationReasonCode.SECURITY_SENSITIVE_CHANGE,
    RULE_CI_WORKFLOW: EscalationReasonCode.CI_WORKFLOW_CHANGE,
    RULE_DEPENDENCY_CHANGE: EscalationReasonCode.DEPENDENCY_CHANGE,
    RULE_BROAD_SCOPE: EscalationReasonCode.BROAD_CHANGE_SCOPE,
    RULE_RESTRICTED_TOOL: EscalationReasonCode.RESTRICTED_TOOL_USED,
    RULE_HIGH_RETRY_COUNT: EscalationReasonCode.MAX_RETRY_SUCCESS_WITH_UNCERTAINTY,
    RULE_DEFAULT_ESCALATION: EscalationReasonCode.POLICY_UNCERTAINTY,
    RULE_ENGINE_FAILURE: EscalationReasonCode.POLICY_UNCERTAINTY,
}


def map_reason_codes(
    policy_decision: PolicyDecision,
    categories: tuple[FileCategory, ...],
) -> tuple[EscalationReasonCode, ...]:
    codes: list[EscalationReasonCode] = []
    for rule in policy_decision.matched_rules:
        code = _RULE_TO_REASON.get(rule)
        if code and code not in codes:
            codes.append(code)
    if FileCategory.INFRASTRUCTURE in categories and EscalationReasonCode.INFRASTRUCTURE_CHANGE not in codes:
        codes.append(EscalationReasonCode.INFRASTRUCTURE_CHANGE)
    if FileCategory.MIGRATION in categories and EscalationReasonCode.DATABASE_MIGRATION not in codes:
        codes.append(EscalationReasonCode.DATABASE_MIGRATION)
    if FileCategory.UNKNOWN in categories and EscalationReasonCode.UNKNOWN_CHANGE_CATEGORY not in codes:
        codes.append(EscalationReasonCode.UNKNOWN_CHANGE_CATEGORY)
    if FileCategory.CONFIGURATION in categories and EscalationReasonCode.PRODUCTION_CONFIG_CHANGE not in codes:
        # only escalate config as production-config when infra/deploy markers present elsewhere
        if any(c in categories for c in (FileCategory.INFRASTRUCTURE, FileCategory.CI)):
            codes.append(EscalationReasonCode.PRODUCTION_CONFIG_CHANGE)
    if not codes:
        codes.append(EscalationReasonCode.OTHER_POLICY_ESCALATION)
    return tuple(codes)


def build_checklist(reason_codes: tuple[EscalationReasonCode, ...]) -> tuple[str, ...]:
    items: list[str] = []

    def add(text: str) -> None:
        if text not in items:
            items.append(text)

    codes = set(reason_codes)
    if codes & {
        EscalationReasonCode.AUTHORIZATION_CHANGE,
        EscalationReasonCode.SECURITY_SENSITIVE_CHANGE,
    }:
        add("Confirm intended privilege boundaries")
        add("Review deny paths")
        add("Review authentication assumptions")
        add("Review authorization checks")
        add("Confirm negative tests exist")
        add("Confirm no privilege broadening outside intended scope")
    if EscalationReasonCode.CI_WORKFLOW_CHANGE in codes:
        add("Review workflow permissions")
        add("Review secrets usage")
        add("Review trigger events")
        add("Review external actions")
        add("Review shell/script changes")
    if EscalationReasonCode.DEPENDENCY_CHANGE in codes:
        add("Review dependency purpose")
        add("Review version delta")
        add("Review lockfile changes")
        add("Review security implications")
    if codes & {
        EscalationReasonCode.INFRASTRUCTURE_CHANGE,
        EscalationReasonCode.PRODUCTION_CONFIG_CHANGE,
        EscalationReasonCode.DATABASE_MIGRATION,
    }:
        add("Review blast radius")
        add("Review permissions/IAM")
        add("Review environment targeting")
        add("Review rollback path")
    if EscalationReasonCode.BROAD_CHANGE_SCOPE in codes:
        add("Confirm change scope is intentional")
        add("Review cross-module interactions")
    if EscalationReasonCode.RESTRICTED_TOOL_USED in codes:
        add("Review restricted tool invocations and side effects")
    if codes & {
        EscalationReasonCode.POLICY_UNCERTAINTY,
        EscalationReasonCode.UNKNOWN_CHANGE_CATEGORY,
        EscalationReasonCode.OTHER_POLICY_ESCALATION,
        EscalationReasonCode.MAX_RETRY_SUCCESS_WITH_UNCERTAINTY,
    }:
        add("Confirm repair intent matches observed failure")
        add("Review residual uncertainty before approving")
    if not items:
        add("Review proposal and evaluation evidence")
        add("Confirm residual risk is acceptable")
    return tuple(items)


def build_unresolved_questions(
    reason_codes: tuple[EscalationReasonCode, ...],
    evaluation: EvaluationResult,
) -> tuple[str, ...]:
    qs: list[str] = []
    codes = set(reason_codes)
    if EscalationReasonCode.AUTHORIZATION_CHANGE in codes or EscalationReasonCode.SECURITY_SENSITIVE_CHANGE in codes:
        qs.append("Does this authorization change preserve all existing role boundaries?")
        qs.append("Are negative authorization cases sufficiently covered?")
    if EscalationReasonCode.CI_WORKFLOW_CHANGE in codes:
        qs.append("Is the modified workflow permitted to access repository secrets?")
        qs.append("Do workflow permissions match least-privilege intent?")
    if EscalationReasonCode.DEPENDENCY_CHANGE in codes:
        qs.append("Is the dependency change acceptable under project policy?")
    if EscalationReasonCode.DATABASE_MIGRATION in codes:
        qs.append("Is the migration reversible and safe for target environments?")
    if EscalationReasonCode.INFRASTRUCTURE_CHANGE in codes:
        qs.append("What is the blast radius of this infrastructure change?")
    if EscalationReasonCode.MAX_RETRY_SUCCESS_WITH_UNCERTAINTY in codes:
        qs.append("Why did earlier attempts fail, and does that indicate residual flakiness?")
    if EscalationReasonCode.UNKNOWN_CHANGE_CATEGORY in codes:
        qs.append("What is the intended category and risk profile of the unknown path?")
    # Evidence-backed evaluation gaps
    for check in evaluation.checks:
        if check.status.value in {"NOT_RUN", "UNAVAILABLE", "SKIPPED"}:
            qs.append(f"Should check '{check.name}' ({check.status.value}) be executed before approval?")
            break
    return tuple(qs[:6])


def patch_line_stats(patch: str) -> dict[str, int]:
    added = 0
    removed = 0
    for line in (patch or "").splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return {"added": added, "removed": removed, "files_touched_estimate": 0}


def _sanitize(text: str, limit: int | None = None) -> str:
    cleaned, _ = sanitize_text(text or "")
    if limit is not None and len(cleaned) > limit:
        return cleaned[: max(0, limit - 24)] + "\n...[truncated]"
    return cleaned


def validate_escalation_inputs(
    *,
    run_id: str,
    policy_decision: PolicyDecision | None,
    proposal: RepairProposal | None,
    evaluation: EvaluationResult | None,
    affected_files: tuple[str, ...] | None,
) -> EvidenceCompleteness:
    missing: list[str] = []
    if not run_id:
        missing.append("run_id")
    if policy_decision is None:
        missing.append("policy_decision")
    elif policy_decision.outcome is not PolicyOutcome.ESCALATE:
        missing.append("policy_outcome_not_escalate")
    if proposal is None:
        missing.append("repair_proposal")
    if evaluation is None:
        missing.append("evaluation_result")
    if affected_files is None:
        missing.append("affected_files")
    if missing:
        return EvidenceCompleteness(EvidenceCompletenessStatus.INCOMPLETE, tuple(missing))
    partial: list[str] = []
    assert proposal is not None and evaluation is not None
    if not (proposal.patch or "").strip():
        partial.append("proposal_patch")
    if not evaluation.checks:
        partial.append("evaluation_checks")
    if not affected_files:
        # explicit empty is allowed; note it
        pass
    if partial:
        return EvidenceCompleteness(EvidenceCompletenessStatus.PARTIAL, tuple(partial))
    return EvidenceCompleteness(EvidenceCompletenessStatus.COMPLETE, ())


class HumanEscalationBuilder:
    """Deterministic assembly of a human-review package from structured evidence."""

    def build(
        self,
        *,
        run_id: str,
        policy_decision: PolicyDecision,
        proposal: RepairProposal,
        evaluation: EvaluationResult,
        attempts: list[AttemptRecord],
        classification: FailureClassification | None = None,
        event: FailureEvent | None = None,
        policy_context_categories: tuple[FileCategory, ...] | None = None,
        policy_context_scope: ChangeScope | None = None,
    ) -> HumanEscalation:
        if policy_decision.outcome is not PolicyOutcome.ESCALATE:
            raise ValueError("HumanEscalationBuilder requires PolicyOutcome.ESCALATE")

        files = tuple(proposal.files_changed)
        completeness = validate_escalation_inputs(
            run_id=run_id,
            policy_decision=policy_decision,
            proposal=proposal,
            evaluation=evaluation,
            affected_files=files,
        )
        categories = policy_context_categories or tuple(classify_file(f) for f in files)
        scope = policy_context_scope or classify_scope(files)
        reasons = map_reason_codes(policy_decision, categories)
        checklist = build_checklist(reasons)
        questions = build_unresolved_questions(reasons, evaluation)
        stats = patch_line_stats(proposal.patch)
        stats["files_touched_estimate"] = len(files)

        failure_summary = self._failure_summary(event, classification)
        proposal_summary = self._proposal_summary(proposal, categories, scope, stats)
        evaluation_summary = self._evaluation_summary(evaluation)
        attempt_summary = self._attempt_summary(attempts)
        policy_summary = self._policy_summary(policy_decision)
        summary = self._main_summary(reasons, evaluation, files, attempts, policy_decision)

        escalation_id = new_id("esc")
        refs = (
            EvidenceRef("proposal", proposal.proposal_id),
            EvidenceRef("evaluation", f"eval:{evaluation.run_id}"),
            EvidenceRef("policy", f"policy:{policy_decision.timestamp}"),
            *[EvidenceRef("attempt", f"attempt-{a.attempt_number}") for a in attempts[-3:]],
        )

        return HumanEscalation(
            escalation_id=escalation_id,
            run_id=run_id,
            reason_codes=reasons,
            summary=_sanitize(summary, 4_000),
            policy_outcome=policy_decision.outcome.value,
            matched_policy_rules=policy_decision.matched_rules,
            risk_level=policy_decision.risk_level,
            failure_summary=_sanitize(failure_summary, 2_000),
            proposed_change_summary=_sanitize(proposal_summary, 2_000),
            affected_files=files if files else ("(none)",),
            file_categories=tuple(c.value for c in categories),
            change_scope=scope,
            evaluation_summary=_sanitize(evaluation_summary, 2_000),
            attempt_summary=_sanitize(attempt_summary, 3_000),
            policy_summary=_sanitize(policy_summary, 2_000),
            unresolved_questions=tuple(_sanitize(q, 400) for q in questions),
            reviewer_checklist=checklist,
            reviewer_actions=(
                ReviewerAction.APPROVE,
                ReviewerAction.REJECT,
                ReviewerAction.REQUEST_CHANGES,
                ReviewerAction.DEFER,
            ),
            evidence_refs=refs,
            evidence_completeness=completeness,
            patch_stats=stats,
        )

    @staticmethod
    def _failure_summary(
        event: FailureEvent | None,
        classification: FailureClassification | None,
    ) -> str:
        if event is None:
            return "Original failure:\n(unavailable)"
        msg = _sanitize(event.message, 240)
        lines = [
            "Original failure:",
            f"{event.workflow}/{event.job} step={event.failed_step}",
            f"Classification:\n{classification.category if classification else 'unknown'}",
            f"Observed error:\n{msg}",
        ]
        if event.log_excerpt and ("test_" in event.log_excerpt or "::" in event.log_excerpt):
            hint = next(
                (ln.strip() for ln in event.log_excerpt.splitlines() if ln.strip()),
                "",
            )
            if hint:
                lines.insert(1, f"Failing target:\n{_sanitize(hint, 160)}")
        return "\n".join(lines)

    @staticmethod
    def _proposal_summary(
        proposal: RepairProposal,
        categories: tuple[FileCategory, ...],
        scope: ChangeScope,
        stats: dict[str, int],
    ) -> str:
        intent = _sanitize(proposal.rationale or proposal.expected_effect or "Repair proposal", 200)
        return "\n".join(
            [
                "Proposed change:",
                intent,
                "",
                f"Files changed:\n{len(proposal.files_changed)}",
                "Change categories:",
                ", ".join(c.value for c in categories) or "UNKNOWN",
                f"Scope:\n{scope.value}",
                f"Patch stats:\n+{stats.get('added', 0)} / -{stats.get('removed', 0)} lines",
            ]
        )

    @staticmethod
    def _evaluation_summary(evaluation: EvaluationResult) -> str:
        lines = [
            "Evaluation:",
            "PASS" if evaluation.passed else "FAIL",
            "",
            "Checks:",
        ]
        for check in evaluation.checks:
            lines.append(f"- {check.name}: {check.status.value}")
        if not evaluation.checks:
            lines.append("- (none)")
        return "\n".join(lines)

    @staticmethod
    def _attempt_summary(attempts: list[AttemptRecord]) -> str:
        if not attempts:
            return "Attempts:\n0"
        lines = [f"Attempts:\n{len(attempts)}", ""]
        selected: list[AttemptRecord] = []
        if len(attempts) <= 3:
            selected = list(attempts)
        else:
            selected = [attempts[0], *attempts[1:-1][-1:], attempts[-1]]
            # uniquify while preserving order
            seen: set[int] = set()
            uniq: list[AttemptRecord] = []
            for a in selected:
                if a.attempt_number not in seen:
                    seen.add(a.attempt_number)
                    uniq.append(a)
            selected = uniq
        for a in selected:
            progress = "yes" if a.progress and a.progress.improved else "no"
            lines.extend(
                [
                    f"Attempt {a.attempt_number}:",
                    f"- result: {'PASS' if a.evaluation_passed else 'FAIL'}",
                    f"- proposal_fp: {a.proposal_fingerprint[:12]}",
                    f"- progress: {progress}",
                    f"- disposition: {a.disposition.value}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()

    @staticmethod
    def _policy_summary(policy_decision: PolicyDecision) -> str:
        rule_lines = [f"- {r}" for r in policy_decision.matched_rules] or ["- (none)"]
        reason_lines = [f"- {r}" for r in policy_decision.reasons] or ["- (none)"]
        return "\n".join(
            [
                "Policy outcome:",
                policy_decision.outcome.value,
                "",
                "Matched rules:",
                *rule_lines,
                "",
                f"Risk:\n{policy_decision.risk_level.value}",
                "",
                "Reason:",
                *reason_lines,
            ]
        )

    @staticmethod
    def _main_summary(
        reasons: tuple[EscalationReasonCode, ...],
        evaluation: EvaluationResult,
        files: tuple[str, ...],
        attempts: list[AttemptRecord],
        policy_decision: PolicyDecision,
    ) -> str:
        reason_text = {
            EscalationReasonCode.AUTHORIZATION_CHANGE: "Authorization-related code was modified.",
            EscalationReasonCode.SECURITY_SENSITIVE_CHANGE: "Security-sensitive paths were modified.",
            EscalationReasonCode.CI_WORKFLOW_CHANGE: "CI/CD workflow configuration was modified.",
            EscalationReasonCode.DEPENDENCY_CHANGE: "Dependency manifests or lockfiles were modified.",
            EscalationReasonCode.INFRASTRUCTURE_CHANGE: "Infrastructure-related files were modified.",
            EscalationReasonCode.DATABASE_MIGRATION: "Database migration files were modified.",
            EscalationReasonCode.BROAD_CHANGE_SCOPE: "Change scope is broad across modules/files.",
            EscalationReasonCode.RESTRICTED_TOOL_USED: "Restricted tools were used outside a small scope.",
            EscalationReasonCode.MAX_RETRY_SUCCESS_WITH_UNCERTAINTY: "Repair succeeded only after multiple attempts.",
            EscalationReasonCode.UNKNOWN_CHANGE_CATEGORY: "Changed paths include unknown categories.",
            EscalationReasonCode.POLICY_UNCERTAINTY: "Policy could not confidently auto-approve.",
            EscalationReasonCode.OTHER_POLICY_ESCALATION: "Policy required human review.",
            EscalationReasonCode.PRODUCTION_CONFIG_CHANGE: "Production/configuration surfaces were modified.",
        }
        primary = reasons[0] if reasons else EscalationReasonCode.OTHER_POLICY_ESCALATION
        why = reason_text.get(primary, "Policy required human review.")
        file_lines = "\n".join(f"- {f}" for f in (files or ("(none)",)))
        return "\n".join(
            [
                "Escalation reason:",
                why,
                "",
                "Technical status:",
                "All configured verification checks passed."
                if evaluation.passed
                else "Technical evaluation did not pass.",
                "",
                "Affected files:",
                file_lines,
                "",
                f"Attempts:\n{len(attempts)}",
                "",
                "Policy result:",
                policy_decision.outcome.value,
                "",
                "Why review is required:",
                why,
                "",
                "Remaining uncertainty:",
                "Automated evaluation confirms configured checks but does not prove broader safety properties.",
            ]
        )


@dataclass(frozen=True)
class EscalationArtifacts:
    root: Path
    summary_json: Path
    summary_md: Path
    evidence_index: Path
    proposed_patch: Path
    evaluation_summary: Path


class EscalationArtifactWriter:
    """Write sanitized local review artifacts under artifacts/runs/<run-id>/escalation/."""

    def __init__(self, artifacts_root: Path | None = None, *, max_patch_chars: int = 50_000) -> None:
        self.artifacts_root = Path(artifacts_root) if artifacts_root else Path("artifacts")
        self.max_patch_chars = max_patch_chars

    def write(
        self,
        escalation: HumanEscalation,
        *,
        proposal: RepairProposal,
        evaluation: EvaluationResult,
    ) -> EscalationArtifacts:
        root = self.artifacts_root / "runs" / escalation.run_id / "escalation"
        root.mkdir(parents=True, exist_ok=True)

        summary_json = root / "summary.json"
        summary_md = root / "summary.md"
        evidence_index = root / "evidence-index.json"
        proposed_patch = root / "proposed.patch"
        evaluation_summary = root / "evaluation-summary.json"

        summary_json.write_text(
            json.dumps(escalation.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        summary_md.write_text(render_escalation_markdown(escalation), encoding="utf-8")

        index = {
            "schema_version": ESCALATION_SCHEMA,
            "escalation_id": escalation.escalation_id,
            "run_id": escalation.run_id,
            "refs": [{"kind": r.kind, "ref": r.ref} for r in escalation.evidence_refs],
            "artifacts": {
                "summary_json": str(summary_json.as_posix()),
                "summary_md": str(summary_md.as_posix()),
                "proposed_patch": str(proposed_patch.as_posix()),
                "evaluation_summary": str(evaluation_summary.as_posix()),
            },
            "evidence_completeness": escalation.evidence_completeness.status.value,
        }
        evidence_index.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        patch_text, _ = sanitize_text(proposal.patch or "")
        if len(patch_text) > self.max_patch_chars:
            patch_text = patch_text[: self.max_patch_chars] + "\n...[truncated]\n"
        proposed_patch.write_text(patch_text, encoding="utf-8")

        eval_payload = {
            "run_id": evaluation.run_id,
            "passed": evaluation.passed,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "detail": _sanitize(c.detail, 400),
                }
                for c in evaluation.checks
            ],
            "evidence": [_sanitize(e, 400) for e in evaluation.evidence[:20]],
        }
        evaluation_summary.write_text(
            json.dumps(eval_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return EscalationArtifacts(
            root=root,
            summary_json=summary_json,
            summary_md=summary_md,
            evidence_index=evidence_index,
            proposed_patch=proposed_patch,
            evaluation_summary=evaluation_summary,
        )


def render_escalation_markdown(escalation: HumanEscalation) -> str:
    files = "\n".join(f"- {f}" for f in escalation.affected_files)
    reasons = "\n".join(f"- {c.value}" for c in escalation.reason_codes)
    rules = "\n".join(f"- {r}" for r in escalation.matched_policy_rules) or "- (none)"
    questions = "\n".join(f"- {q}" for q in escalation.unresolved_questions) or "- (none)"
    checklist = "\n".join(f"- [ ] {item}" for item in escalation.reviewer_checklist)
    actions = "\n".join(f"- {a.value}" for a in escalation.reviewer_actions)
    refs = "\n".join(f"- {r.kind}: `{r.ref}`" for r in escalation.evidence_refs)
    stats = escalation.patch_stats
    return "\n".join(
        [
            "# Human Review Required",
            "",
            "## Run",
            "",
            f"`{escalation.run_id}`",
            "",
            f"Escalation ID: `{escalation.escalation_id}`",
            "",
            f"Evidence status: `{escalation.evidence_completeness.status.value}`",
            "",
            "## Escalation Reason",
            "",
            reasons,
            "",
            escalation.summary,
            "",
            "## Original Failure",
            "",
            escalation.failure_summary,
            "",
            "## Proposed Repair",
            "",
            escalation.proposed_change_summary,
            "",
            "### Files",
            "",
            files,
            "",
            f"Patch stats: +{stats.get('added', 0)} / -{stats.get('removed', 0)} lines",
            "",
            "## Technical Evaluation",
            "",
            escalation.evaluation_summary,
            "",
            "## Policy Decision",
            "",
            escalation.policy_summary,
            "",
            "### Matched rules",
            "",
            rules,
            "",
            "## Retry / Attempt History",
            "",
            escalation.attempt_summary,
            "",
            "## Risk Summary",
            "",
            escalation.risk_level.value,
            "",
            "## Unresolved Questions",
            "",
            questions,
            "",
            "## Reviewer Checklist",
            "",
            checklist,
            "",
            "## Evidence References",
            "",
            refs,
            "",
            "## Available Reviewer Actions",
            "",
            actions,
            "",
            "_This package does not recommend a reviewer decision._",
            "",
        ]
    )

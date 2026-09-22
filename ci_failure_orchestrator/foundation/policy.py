"""Phase 8 — deterministic Policy Gate (governance after technical evaluation).

Fail-closed: unexpected engine errors map to ESCALATE, never APPROVE.
Does not apply patches or run human-review workflows (Phase 9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from .models import (
    EvaluationResult,
    FailureClassification,
    RepairProposal,
    ToolRiskLevel,
    utc_now,
)


class PolicyOutcome(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class GovernanceRiskLevel(str, Enum):
    """Deterministic governance risk — not a probabilistic score."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FileCategory(str, Enum):
    SOURCE = "SOURCE"
    TEST = "TEST"
    DOCUMENTATION = "DOCUMENTATION"
    CI = "CI"
    DEPENDENCY = "DEPENDENCY"
    SECURITY = "SECURITY"
    AUTH = "AUTH"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    MIGRATION = "MIGRATION"
    CONFIGURATION = "CONFIGURATION"
    UNKNOWN = "UNKNOWN"


class ChangeScope(str, Enum):
    SMALL = "SMALL"
    MODERATE = "MODERATE"
    BROAD = "BROAD"


@dataclass(frozen=True)
class PolicyViolation:
    rule_id: str
    severity: str
    message: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reasons: tuple[str, ...]
    matched_rules: tuple[str, ...]
    violations: tuple[PolicyViolation, ...]
    risk_level: GovernanceRiskLevel
    evidence: tuple[str, ...] = ()
    explanation: str = ""
    timestamp: str = field(default_factory=utc_now)

    def explain(self) -> str:
        if self.explanation:
            return self.explanation
        rule_lines = [f"- {r}" for r in self.matched_rules] or ["- (none)"]
        evidence_lines = [f"- {e}" for e in self.evidence] or ["- (none)"]
        reason_lines = [f"- {r}" for r in self.reasons] or ["- (none)"]
        lines = [
            f"Policy Decision: {self.outcome.value}",
            "",
            "Matched rules:",
            *rule_lines,
            "",
            "Evidence:",
            *evidence_lines,
            "",
            "Reason:",
            *reason_lines,
        ]
        if self.violations:
            lines.extend(
                [
                    "",
                    "Violations:",
                    *[f"- {v.rule_id}: {v.message}" for v in self.violations],
                ]
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class PolicyContext:
    proposal: RepairProposal
    evaluation: EvaluationResult
    classification: FailureClassification | None
    changed_files: tuple[str, ...]
    tools_used: tuple[str, ...]
    tool_risk_levels: tuple[ToolRiskLevel, ...]
    attempt_count: int = 1
    file_categories: tuple[FileCategory, ...] = ()
    change_scope: ChangeScope = ChangeScope.SMALL
    risk_level: GovernanceRiskLevel = GovernanceRiskLevel.LOW


@dataclass(frozen=True)
class PolicyConfig:
    """Declarative policy configuration (constructor injection; no new framework)."""

    default_outcome: PolicyOutcome = PolicyOutcome.ESCALATE
    forbidden_paths: tuple[str, ...] = (
        ".env",
        "secrets/",
        ".git/",
        "id_rsa",
    )
    escalation_paths: tuple[str, ...] = (
        ".github/workflows/",
        "auth/",
        "infra/",
        "migrations/",
        "deploy/",
    )
    security_path_markers: tuple[str, ...] = (
        "auth/",
        "authorization",
        "permission",
        "secret",
        "crypt",
        "oauth",
        "jwt",
        "credential",
    )
    dependency_filenames: tuple[str, ...] = (
        "requirements.txt",
        "pyproject.toml",
        "poetry.lock",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "Cargo.toml",
        "Cargo.lock",
        "go.mod",
        "go.sum",
    )
    ci_path_prefixes: tuple[str, ...] = (
        ".github/workflows/",
        "Jenkinsfile",
        "azure-pipelines.yml",
        ".gitlab-ci.yml",
    )
    auto_approve_max_files: int = 3
    auto_approve_categories: tuple[FileCategory, ...] = (
        FileCategory.SOURCE,
        FileCategory.TEST,
        FileCategory.DOCUMENTATION,
    )
    auto_approve_risk_levels: tuple[GovernanceRiskLevel, ...] = (GovernanceRiskLevel.LOW,)
    escalate_on_restricted_tools: bool = True
    escalate_when_attempts_at_max: bool = False
    max_attempts_for_escalation: int = 3
    small_scope_max_files: int = 3
    moderate_scope_max_files: int = 8

    def __post_init__(self) -> None:
        if not isinstance(self.default_outcome, PolicyOutcome):
            raise ValueError(f"invalid default_outcome: {self.default_outcome!r}")
        if self.default_outcome is PolicyOutcome.APPROVE:
            raise ValueError("default_outcome must not be APPROVE (conservative)")
        if self.auto_approve_max_files < 1:
            raise ValueError("auto_approve_max_files must be >= 1")
        if self.small_scope_max_files < 1 or self.moderate_scope_max_files < 1:
            raise ValueError("scope thresholds must be >= 1")
        if self.small_scope_max_files > self.moderate_scope_max_files:
            raise ValueError("small_scope_max_files must be <= moderate_scope_max_files")
        if self.max_attempts_for_escalation < 1:
            raise ValueError("max_attempts_for_escalation must be >= 1")
        for level in self.auto_approve_risk_levels:
            if not isinstance(level, GovernanceRiskLevel):
                raise ValueError(f"invalid risk level: {level!r}")
        for cat in self.auto_approve_categories:
            if not isinstance(cat, FileCategory):
                raise ValueError(f"invalid file category: {cat!r}")
        for p in self.forbidden_paths + self.escalation_paths:
            if not p or ".." in p.replace("\\", "/"):
                raise ValueError(f"malformed path pattern: {p!r}")


# Stable rule IDs
RULE_EVALUATION_MUST_PASS = "POL-001-EVALUATION-MUST-PASS"
RULE_FORBIDDEN_PATH = "POL-002-FORBIDDEN-PATH"
RULE_SECURITY_SENSITIVE = "POL-003-SECURITY-SENSITIVE-CHANGE"
RULE_CI_WORKFLOW = "POL-004-CI-WORKFLOW-CHANGE"
RULE_LOW_RISK_AUTO_APPROVE = "POL-005-LOW-RISK-AUTO-APPROVE"
RULE_DEFAULT_ESCALATION = "POL-006-DEFAULT-ESCALATION"
RULE_DEPENDENCY_CHANGE = "POL-007-DEPENDENCY-CHANGE"
RULE_RESTRICTED_TOOL = "POL-008-RESTRICTED-TOOL"
RULE_AUTH_CHANGE = "POL-009-AUTH-CHANGE"
RULE_BROAD_SCOPE = "POL-010-BROAD-SCOPE"
RULE_HIGH_RETRY_COUNT = "POL-011-HIGH-RETRY-COUNT"
RULE_INVALID_PROPOSAL = "POL-012-INVALID-PROPOSAL"
RULE_ENGINE_FAILURE = "POL-013-ENGINE-FAILURE"


DEPENDENCY_BASENAMES = frozenset(
    {
        "requirements.txt",
        "pyproject.toml",
        "poetry.lock",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "cargo.toml",
        "cargo.lock",
        "go.mod",
        "go.sum",
    }
)


def normalize_path(path: str) -> str:
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lower()


def classify_file(path: str) -> FileCategory:
    p = normalize_path(path)
    base = p.rsplit("/", 1)[-1]
    if base in DEPENDENCY_BASENAMES or base.endswith(".lock"):
        return FileCategory.DEPENDENCY
    if (
        p.startswith(".github/workflows/")
        or base in {"jenkinsfile", "azure-pipelines.yml", ".gitlab-ci.yml"}
        or p.endswith("/azure-pipelines.yml")
        or p == "azure-pipelines.yml"
        or p == ".gitlab-ci.yml"
        or p == "jenkinsfile"
    ):
        return FileCategory.CI
    if "/migrations/" in f"/{p}/" or p.startswith("migrations/") or "/alembic/" in f"/{p}/":
        return FileCategory.MIGRATION
    if p.startswith("infra/") or p.startswith("terraform/") or p.startswith("deploy/"):
        return FileCategory.INFRASTRUCTURE
    if (
        p.startswith("auth/")
        or "/auth/" in f"/{p}/"
        or "authorization" in p
        or "permission" in p
    ):
        return FileCategory.AUTH
    if (
        "secret" in p
        or p.startswith("secrets/")
        or "credential" in p
        or base in {".env", "id_rsa"}
        or "crypt" in p
    ):
        return FileCategory.SECURITY
    if (
        p.startswith("tests/")
        or p.startswith("test/")
        or "/tests/" in f"/{p}/"
        or base.startswith("test_")
        or base.endswith("_test.py")
    ):
        return FileCategory.TEST
    if (
        p.startswith("docs/")
        or base.endswith(".md")
        or base in {"readme", "readme.md", "changelog.md"}
    ):
        return FileCategory.DOCUMENTATION
    if (
        p.startswith("src/")
        or p.startswith("ci_failure_orchestrator/")
        or p.endswith((".py", ".ts", ".js", ".go", ".rs"))
    ):
        return FileCategory.SOURCE
    if base.endswith((".yml", ".yaml", ".toml", ".ini", ".cfg", ".json")):
        return FileCategory.CONFIGURATION
    return FileCategory.UNKNOWN


def classify_scope(
    files: tuple[str, ...],
    *,
    small_max: int = 3,
    moderate_max: int = 8,
) -> ChangeScope:
    n = len(files)
    if n == 0:
        return ChangeScope.BROAD
    dirs = {normalize_path(f).rsplit("/", 1)[0] for f in files if "/" in normalize_path(f)}
    if n <= small_max and len(dirs) <= 2:
        return ChangeScope.SMALL
    if n <= moderate_max and len(dirs) <= 4:
        return ChangeScope.MODERATE
    return ChangeScope.BROAD


def classify_risk(
    *,
    categories: tuple[FileCategory, ...],
    scope: ChangeScope,
    tool_risks: tuple[ToolRiskLevel, ...],
    files: tuple[str, ...],
) -> GovernanceRiskLevel:
    cats = set(categories)
    if FileCategory.SECURITY in cats:
        return GovernanceRiskLevel.CRITICAL
    if any(normalize_path(f).startswith((".env", "secrets/")) or "id_rsa" in normalize_path(f) for f in files):
        return GovernanceRiskLevel.CRITICAL
    if FileCategory.AUTH in cats or FileCategory.CI in cats:
        return GovernanceRiskLevel.HIGH
    if FileCategory.INFRASTRUCTURE in cats or FileCategory.MIGRATION in cats:
        return GovernanceRiskLevel.HIGH
    if FileCategory.DEPENDENCY in cats:
        return GovernanceRiskLevel.MEDIUM
    if ToolRiskLevel.RESTRICTED in tool_risks and scope is not ChangeScope.SMALL:
        return GovernanceRiskLevel.MEDIUM
    if FileCategory.UNKNOWN in cats or scope is ChangeScope.BROAD:
        return GovernanceRiskLevel.MEDIUM
    if scope is ChangeScope.MODERATE:
        return GovernanceRiskLevel.MEDIUM
    if cats <= {FileCategory.SOURCE, FileCategory.TEST, FileCategory.DOCUMENTATION}:
        return GovernanceRiskLevel.LOW
    return GovernanceRiskLevel.MEDIUM


def build_policy_context(
    *,
    proposal: RepairProposal,
    evaluation: EvaluationResult,
    classification: FailureClassification | None,
    tools_used: tuple[str, ...] = (),
    tool_risk_levels: tuple[ToolRiskLevel, ...] = (),
    attempt_count: int = 1,
    config: PolicyConfig | None = None,
) -> PolicyContext:
    cfg = config or PolicyConfig()
    files = tuple(proposal.files_changed)
    categories = tuple(classify_file(f) for f in files)
    scope = classify_scope(
        files,
        small_max=cfg.small_scope_max_files,
        moderate_max=cfg.moderate_scope_max_files,
    )
    risk = classify_risk(
        categories=categories,
        scope=scope,
        tool_risks=tool_risk_levels,
        files=files,
    )
    return PolicyContext(
        proposal=proposal,
        evaluation=evaluation,
        classification=classification,
        changed_files=files,
        tools_used=tools_used,
        tool_risk_levels=tool_risk_levels,
        attempt_count=attempt_count,
        file_categories=categories,
        change_scope=scope,
        risk_level=risk,
    )


class PolicyEngine(Protocol):
    def evaluate(self, context: PolicyContext) -> PolicyDecision: ...


class StaticPolicyEngine:
    """Deterministic rule engine. Precedence: hard reject → escalate → allow → default."""

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def evaluate(self, context: PolicyContext) -> PolicyDecision:
        try:
            return self._evaluate(context)
        except Exception as exc:  # noqa: BLE001 — fail closed
            return PolicyDecision(
                outcome=PolicyOutcome.ESCALATE,
                reasons=(f"policy_engine_error:{type(exc).__name__}",),
                matched_rules=(RULE_ENGINE_FAILURE,),
                violations=(
                    PolicyViolation(
                        RULE_ENGINE_FAILURE,
                        "HIGH",
                        "Policy engine failed closed",
                        (str(exc)[:200],),
                    ),
                ),
                risk_level=GovernanceRiskLevel.HIGH,
                evidence=("fail_closed=true",),
                explanation=(
                    "Policy Decision: ESCALATE\n\n"
                    "Matched rules:\n- POL-013-ENGINE-FAILURE\n\n"
                    "Reason:\n- Policy engine error; fail-closed escalation."
                ),
            )

    def _evaluate(self, context: PolicyContext) -> PolicyDecision:
        cfg = self.config
        matched: list[str] = []
        violations: list[PolicyViolation] = []
        reasons: list[str] = []
        evidence = [
            f"evaluation_passed={context.evaluation.passed}",
            f"files={len(context.changed_files)}",
            f"scope={context.change_scope.value}",
            f"risk={context.risk_level.value}",
            f"categories={','.join(c.value for c in context.file_categories) or 'none'}",
            f"tools={','.join(context.tools_used) or 'none'}",
            f"attempts={context.attempt_count}",
            *[f"file:{f}" for f in context.changed_files[:8]],
        ]

        # --- 1. Hard reject ---
        if not context.evaluation.passed:
            matched.append(RULE_EVALUATION_MUST_PASS)
            violations.append(
                PolicyViolation(
                    RULE_EVALUATION_MUST_PASS,
                    "HIGH",
                    "Evaluation did not pass; cannot approve",
                    ("evaluation.passed=False",),
                )
            )
            return self._decision(
                PolicyOutcome.REJECT,
                matched,
                violations,
                reasons=("evaluation_must_pass",),
                risk=max_risk(context.risk_level, GovernanceRiskLevel.HIGH),
                evidence=evidence,
                detail="Technical evaluation failed; governance rejects approval.",
            )

        if not context.changed_files or not (context.proposal.patch or "").strip():
            matched.append(RULE_INVALID_PROPOSAL)
            violations.append(
                PolicyViolation(
                    RULE_INVALID_PROPOSAL,
                    "HIGH",
                    "Malformed or empty proposal",
                    (),
                )
            )
            return self._decision(
                PolicyOutcome.REJECT,
                matched,
                violations,
                reasons=("invalid_proposal",),
                risk=GovernanceRiskLevel.HIGH,
                evidence=evidence,
                detail="Proposal is empty or has no changed files.",
            )

        forbidden_hits = self._matching_paths(context.changed_files, cfg.forbidden_paths)
        if forbidden_hits:
            matched.append(RULE_FORBIDDEN_PATH)
            violations.append(
                PolicyViolation(
                    RULE_FORBIDDEN_PATH,
                    "HIGH",
                    "Proposal modifies forbidden path",
                    tuple(forbidden_hits),
                )
            )
            return self._decision(
                PolicyOutcome.REJECT,
                matched,
                violations,
                reasons=("forbidden_path",),
                risk=GovernanceRiskLevel.CRITICAL,
                evidence=list(evidence) + [f"forbidden:{h}" for h in forbidden_hits],
                detail=f"Forbidden path(s): {', '.join(forbidden_hits)}.",
            )

        # --- 2. Mandatory escalation ---
        escalate_reasons: list[str] = []

        auth_hits = [
            f
            for f, c in zip(context.changed_files, context.file_categories)
            if c is FileCategory.AUTH
        ]
        if auth_hits or self._path_contains_markers(context.changed_files, cfg.security_path_markers):
            # Distinguish AUTH vs broader security markers
            if auth_hits:
                matched.append(RULE_AUTH_CHANGE)
                escalate_reasons.append("auth_code_modified")
            else:
                matched.append(RULE_SECURITY_SENSITIVE)
                escalate_reasons.append("security_sensitive_path")

        sec_cats = [
            f
            for f, c in zip(context.changed_files, context.file_categories)
            if c is FileCategory.SECURITY
        ]
        if sec_cats and RULE_SECURITY_SENSITIVE not in matched:
            matched.append(RULE_SECURITY_SENSITIVE)
            escalate_reasons.append("security_category_file")

        ci_hits = [
            f
            for f, c in zip(context.changed_files, context.file_categories)
            if c is FileCategory.CI
        ] or self._matching_paths(context.changed_files, cfg.ci_path_prefixes)
        if ci_hits:
            matched.append(RULE_CI_WORKFLOW)
            escalate_reasons.append("ci_workflow_modified")

        dep_hits = [
            f
            for f, c in zip(context.changed_files, context.file_categories)
            if c is FileCategory.DEPENDENCY
        ]
        if dep_hits:
            matched.append(RULE_DEPENDENCY_CHANGE)
            escalate_reasons.append("dependency_manifest_or_lockfile")

        esc_path_hits = self._matching_paths(context.changed_files, cfg.escalation_paths)
        if esc_path_hits and not escalate_reasons:
            matched.append(RULE_SECURITY_SENSITIVE)
            escalate_reasons.append("escalation_path_prefix")

        if (
            cfg.escalate_on_restricted_tools
            and ToolRiskLevel.RESTRICTED in context.tool_risk_levels
            and context.change_scope is not ChangeScope.SMALL
        ):
            matched.append(RULE_RESTRICTED_TOOL)
            escalate_reasons.append("restricted_tool_with_non_small_scope")

        if context.change_scope is ChangeScope.BROAD:
            matched.append(RULE_BROAD_SCOPE)
            escalate_reasons.append("broad_change_scope")

        if (
            cfg.escalate_when_attempts_at_max
            and context.attempt_count >= cfg.max_attempts_for_escalation
        ):
            matched.append(RULE_HIGH_RETRY_COUNT)
            escalate_reasons.append("high_retry_count")

        if FileCategory.UNKNOWN in context.file_categories:
            escalate_reasons.append("unknown_file_category")
            if RULE_DEFAULT_ESCALATION not in matched:
                matched.append(RULE_DEFAULT_ESCALATION)

        if FileCategory.INFRASTRUCTURE in context.file_categories or FileCategory.MIGRATION in context.file_categories:
            escalate_reasons.append("infra_or_migration")
            if RULE_SECURITY_SENSITIVE not in matched and RULE_BROAD_SCOPE not in matched:
                matched.append(RULE_BROAD_SCOPE)

        if escalate_reasons:
            # Deduplicate matched while preserving order
            uniq_matched = tuple(dict.fromkeys(matched))
            return self._decision(
                PolicyOutcome.ESCALATE,
                list(uniq_matched),
                violations,
                reasons=tuple(escalate_reasons),
                risk=max_risk(context.risk_level, GovernanceRiskLevel.HIGH),
                evidence=evidence,
                detail="; ".join(escalate_reasons),
            )

        # --- 3. Explicit allow (low-risk auto-approve) ---
        if self._eligible_auto_approve(context, cfg):
            matched.append(RULE_LOW_RISK_AUTO_APPROVE)
            return self._decision(
                PolicyOutcome.APPROVE,
                matched,
                violations,
                reasons=("low_risk_auto_approve",),
                risk=context.risk_level,
                evidence=evidence,
                detail="Low-risk source/test/docs change within auto-approve limits.",
            )

        # --- 4. Default conservative ---
        matched.append(RULE_DEFAULT_ESCALATION)
        return self._decision(
            cfg.default_outcome,
            matched,
            violations,
            reasons=("default_conservative",),
            risk=max_risk(context.risk_level, GovernanceRiskLevel.MEDIUM),
            evidence=evidence,
            detail="No explicit allow rule matched; default escalation.",
        )

    def _eligible_auto_approve(self, context: PolicyContext, cfg: PolicyConfig) -> bool:
        if context.risk_level not in cfg.auto_approve_risk_levels:
            return False
        if len(context.changed_files) > cfg.auto_approve_max_files:
            return False
        if context.change_scope is not ChangeScope.SMALL:
            return False
        if not context.file_categories:
            return False
        if any(c not in cfg.auto_approve_categories for c in context.file_categories):
            return False
        if ToolRiskLevel.RESTRICTED in context.tool_risk_levels and len(context.changed_files) > 1:
            # Restricted tools ok for tiny single-file source repairs under LOW risk only if still SMALL
            pass
        return True

    @staticmethod
    def _matching_paths(files: tuple[str, ...], patterns: tuple[str, ...]) -> list[str]:
        hits: list[str] = []
        for f in files:
            nf = normalize_path(f)
            for pat in patterns:
                p = normalize_path(pat)
                if nf == p or nf.startswith(p) or p in nf:
                    hits.append(f)
                    break
        return hits

    @staticmethod
    def _path_contains_markers(files: tuple[str, ...], markers: tuple[str, ...]) -> bool:
        for f in files:
            nf = normalize_path(f)
            for m in markers:
                if normalize_path(m) in nf:
                    return True
        return False

    @staticmethod
    def _decision(
        outcome: PolicyOutcome,
        matched: list[str],
        violations: list[PolicyViolation],
        *,
        reasons: tuple[str, ...],
        risk: GovernanceRiskLevel,
        evidence: list[str] | tuple[str, ...],
        detail: str,
    ) -> PolicyDecision:
        uniq = tuple(dict.fromkeys(matched))
        explanation = (
            f"Policy Decision: {outcome.value}\n\n"
            f"Matched rules:\n"
            + ("\n".join(f"- {r}" for r in uniq) or "- (none)")
            + "\n\nEvidence:\n"
            + ("\n".join(f"- {e}" for e in evidence) or "- (none)")
            + f"\n\nReason:\n- {detail}"
        )
        return PolicyDecision(
            outcome=outcome,
            reasons=reasons,
            matched_rules=uniq,
            violations=tuple(violations),
            risk_level=risk,
            evidence=tuple(evidence),
            explanation=explanation,
        )


_RISK_ORDER = {
    GovernanceRiskLevel.LOW: 0,
    GovernanceRiskLevel.MEDIUM: 1,
    GovernanceRiskLevel.HIGH: 2,
    GovernanceRiskLevel.CRITICAL: 3,
}


def max_risk(a: GovernanceRiskLevel, b: GovernanceRiskLevel) -> GovernanceRiskLevel:
    return a if _RISK_ORDER[a] >= _RISK_ORDER[b] else b

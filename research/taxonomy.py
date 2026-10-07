"""Label sets shared by the dataset, baselines, metrics and error analysis."""

from __future__ import annotations

from ci_failure_orchestrator.service.verification import WAIVABLE_GATES

__all__ = [
    "CANDIDATE_LABELS",
    "CLASSIFIER_TO_RESEARCH",
    "CONFIDENCE_LEVELS",
    "ERROR_MITIGATIONS",
    "ERROR_TAXONOMY",
    "FAILURE_CATEGORIES",
    "RECOMMENDED_ACTIONS",
    "WAIVABLE_GATES",
    "to_research_category",
]

FAILURE_CATEGORIES: tuple[str, ...] = (
    "dependency",
    "compilation_or_syntax",
    "lint_or_formatting",
    "unit_test",
    "integration_test",
    "configuration",
    "security_or_policy",
    "flaky_or_nondeterministic",
    "timeout_or_resource",
    "infrastructure_or_environment",
    "cross_job_dependency",
    "other",
)

# The product classifier has no unit/integration distinction and no cross-job class, so B0, B3 and P
# can never predict integration_test or cross_job_dependency. This is reported as a limitation.
CLASSIFIER_TO_RESEARCH: dict[str, str] = {
    "test_failure": "unit_test",
    "lint_failure": "lint_or_formatting",
    "type_failure": "compilation_or_syntax",
    "build_failure": "compilation_or_syntax",
    "network_failure": "infrastructure_or_environment",
    "dependency_failure": "dependency",
    "flaky_failure": "flaky_or_nondeterministic",
    "infrastructure_failure": "infrastructure_or_environment",
    "security_scan_failure": "security_or_policy",
    "timeout_failure": "timeout_or_resource",
    "configuration_failure": "configuration",
    "environment_failure": "infrastructure_or_environment",
    "unknown": "other",
}

CONFIDENCE_LEVELS: tuple[str, ...] = ("low", "medium", "high")

RECOMMENDED_ACTIONS: tuple[str, ...] = (
    "repair_code",
    "repair_test",
    "repair_dependency",
    "repair_configuration",
    "retry_or_quarantine",
    "escalate_to_human",
    "block_and_escalate",
    "investigate_infrastructure",
)

CANDIDATE_LABELS: tuple[str, ...] = ("correct", "fake_fix", "semantically_wrong", "regression", "no_op")

ERROR_TAXONOMY: tuple[str, ...] = (
    "wrong_failure_class",
    "wrong_root_cause",
    "insufficient_evidence",
    "context_selection_failure",
    "dependency_reasoning_failure",
    "hallucinated_repair",
    "repair_did_not_fix_original_failure",
    "regression_introduced",
    "unsafe_repair",
    "policy_false_positive",
    "policy_false_negative",
    "verification_gap",
    "environment_mismatch",
    "flaky_or_nondeterministic",
    "unknown",
)

ERROR_MITIGATIONS: dict[str, str] = {
    "wrong_failure_class": "Extend classifier rules or model prompt with the missed signal; add a dev case.",
    "wrong_root_cause": "Inspect stage ordering and upstream evidence; add cascade cases of this shape.",
    "insufficient_evidence": "Capture longer or more targeted log excerpts at collection time.",
    "context_selection_failure": "Revise the bounded context policy (new version; never edit in place).",
    "dependency_reasoning_failure": "Check pipeline graph completeness; add missing depends_on edges.",
    "hallucinated_repair": "Reject outputs that reference files or symbols absent from the repository.",
    "repair_did_not_fix_original_failure": "Require the exact failing test to be rerun after the patch.",
    "regression_introduced": "Run the full regression suite before acceptance.",
    "unsafe_repair": "Strengthen verification-integrity rules for this fake-fix shape.",
    "policy_false_positive": "Review the policy rule; a correct repair was blocked.",
    "policy_false_negative": "Add a policy or integrity rule; an incorrect repair was not blocked.",
    "verification_gap": "Add an independent oracle (behavioural invariant or hidden test) for this behaviour.",
    "environment_mismatch": "Pin the environment or mark the case environment-dependent.",
    "flaky_or_nondeterministic": "Rerun to confirm; quarantine evidence rather than repairing code.",
    "unknown": "Manual review required.",
}


def to_research_category(classifier_category: str) -> str:
    """Map a product classifier category to the research taxonomy; unknown values map to ``other``."""
    return CLASSIFIER_TO_RESEARCH.get(classifier_category, "other")

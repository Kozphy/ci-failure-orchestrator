"""Evidence-backed Definition of Done evaluation.

This module intentionally separates an agent's completion claim from release
readiness. Callers provide machine-readable evidence and the evaluator derives
whether every required production gate is satisfied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


REQUIRED_GATES: dict[str, tuple[Any, ...]] = {
    "requirements.acceptance_criteria": ("pass",),
    "code.complete": (True,),
    "code.lint": ("pass",),
    "code.typecheck": ("pass",),
    "code.static_analysis": ("pass",),
    "tests.unit": ("pass",),
    "tests.integration": ("pass",),
    "tests.regression": ("pass",),
    "tests.failure_paths": ("pass",),
    "tests.e2e": ("pass", "not_applicable"),
    "docs.public_api": ("updated", "not_applicable"),
    "docs.docstrings": ("updated",),
    "docs.architecture": ("updated", "not_applicable"),
    "docs.safety": ("updated", "not_applicable"),
    "docs.runbook": ("updated", "not_applicable"),
    "docs.limitations": ("documented", "none"),
    "security.secrets_scan": ("pass",),
    "security.dependency_scan": ("pass",),
    "security.vulnerability_scan": ("pass",),
    "security.safety_invariants": ("pass",),
    "operations.observability": ("verified",),
    "operations.rollback": ("verified", "documented"),
    "operations.deployment": ("verified", "not_applicable"),
    "operations.canary": ("verified", "not_applicable"),
    "reproducibility.dependencies_locked": (True,),
    "reproducibility.build_reproducible": (True,),
    "reproducibility.test_environment_reproducible": (True,),
    "reproducibility.artifact_provenance": ("recorded",),
    "governance.issue_linked": (True,),
    "governance.pr_linked": (True,),
    "governance.review_satisfied": (True,),
    "governance.audit_evidence": ("generated",),
    "governance.high_risk_findings": (0,),
    "ci.required_checks": ("pass",),
    "ci.policy_gate": ("pass",),
}


@dataclass(frozen=True)
class GateFailure:
    """Describe one missing or unsatisfied Definition of Done gate."""

    path: str
    expected: tuple[Any, ...]
    actual: Any

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable failure representation."""

        return {"path": self.path, "expected": list(self.expected), "actual": self.actual}


@dataclass(frozen=True)
class DefinitionOfDoneResult:
    """Derived completion state produced from independent evidence."""

    status: str
    failures: tuple[GateFailure, ...]

    @property
    def done(self) -> bool:
        """Return True only when all required gates are satisfied."""

        return self.status == "PRODUCTION_DONE"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable result for CI artifacts and APIs."""

        return {
            "status": self.status,
            "done": self.done,
            "missing_or_failed_gates": [failure.to_dict() for failure in self.failures],
        }


def _read_path(evidence: Mapping[str, Any], path: str) -> Any:
    """Read a dotted evidence path, returning None when any segment is absent."""

    value: Any = evidence
    for segment in path.split("."):
        if not isinstance(value, Mapping) or segment not in value:
            return None
        value = value[segment]
    return value


def evaluate_definition_of_done(
    evidence: Mapping[str, Any],
    *,
    required_gates: Mapping[str, tuple[Any, ...]] = REQUIRED_GATES,
) -> DefinitionOfDoneResult:
    """Derive production completion from evidence using fail-closed semantics.

    Missing evidence is treated as a failed gate. Agents cannot bypass a gate by
    omitting it, and callers may inject an alternate gate map for repository-
    specific policy or unit tests.
    """

    failures: list[GateFailure] = []
    for path, expected in required_gates.items():
        actual = _read_path(evidence, path)
        if actual not in expected:
            failures.append(GateFailure(path=path, expected=expected, actual=actual))

    return DefinitionOfDoneResult(
        status="PRODUCTION_DONE" if not failures else "NOT_DONE",
        failures=tuple(failures),
    )

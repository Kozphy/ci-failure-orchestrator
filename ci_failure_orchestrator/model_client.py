from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

# ---------------------------------------------------------------------------
# Provider-neutral model client
# ---------------------------------------------------------------------------

class StructuredModelClient(Protocol):
    """Provider-neutral structured-completion interface.

    The model must return a parsed JSON object. Providers that only emit text
    are responsible for parsing + validation before this protocol is satisfied.
    """

    def complete(self, payload: dict[str, Any]) -> Mapping[str, Any]: ...


# ---------------------------------------------------------------------------
# Structured diagnosis model
# ---------------------------------------------------------------------------

_DIAGNOSTIC_INCIDENT_TYPES = frozenset({
    "TYPE_ERROR",
    "BUILD_ERROR",
    "NETWORK_ERROR",
    "DEPENDENCY_ERROR",
    "TEST_ASSERTION",
    "FLAKY_TEST",
    "PACKAGE_ERROR",
    "DEPLOYMENT_ERROR",
    "SECURITY_ERROR",
    "RUNTIME_ERROR",
    "UNKNOWN",
})

_SUPPORTED_RECOMMENDED_ACTIONS = frozenset({
    "inspect",
    "quarantine_test",
    "targeted_repair",
    "dependency_reconcile",
    "build_config_fix",
    "safe_dependency_upgrade",
    "bounded_infra_retry",
    "escalate",
})


@dataclass(frozen=True)
class StructuredDiagnosis:
    """Validated, model-backed diagnosis that the harness trusts only as a hypothesis.

    The deterministic system remains the authority for evidence, policy, and
    execution. This object is a proposal, not a permission.
    """

    incident_type: str
    confidence: float
    hypothesis: str
    evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...]
    recommended_action: str
    human_review_required: bool
    model: str
    raw_model_id: str | None = None
    evaluated_at: str | None = None


    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_type": self.incident_type,
            "confidence": self.confidence,
            "hypothesis": self.hypothesis,
            "evidence_refs": list(self.evidence_refs),
            "limitations": list(self.limitations),
            "recommended_action": self.recommended_action,
            "human_review_required": self.human_review_required,
            "model": self.model,
            "raw_model_id": self.raw_model_id,
            "evaluated_at": self.evaluated_at,
        }


class DiagnosisValidationError(ValueError):
    """Raised when model output cannot be trusted and must fail closed."""


def validate_and_build_diagnosis(
    raw: Mapping[str, Any],
    *,
    model: str,
    raw_model_id: str | None = None,
    evaluated_at: str | None = None,
) -> StructuredDiagnosis:
    """Convert a model payload into a validated StructuredDiagnosis.

    Invalid output fails closed toward ESCALATE with low confidence and
    human review required.
    """

    def _require_str(key: str) -> str:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise DiagnosisValidationError(f"missing or non-string field: {key}")
        return value.strip()

    def _require_float(key: str) -> float:
        value = raw.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise DiagnosisValidationError(f"missing or non-numeric field: {key}")
        return float(value)

    def _require_str_list(key: str) -> list[str]:
        value = raw.get(key)
        if not isinstance(value, list):
            raise DiagnosisValidationError(f"missing or non-list field: {key}")
        out: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise DiagnosisValidationError(f"invalid item in list field {key!r}")
            out.append(item.strip())
        return out

    incident_type = _require_str("incident_type")
    confidence = _require_float("confidence")
    hypothesis = _require_str("hypothesis")
    recommended_action = _require_str("recommended_action")
    limitations = tuple(_require_str_list("limitations"))
    evidence_refs = tuple(_require_str_list("evidence_refs"))

    if incident_type not in _DIAGNOSTIC_INCIDENT_TYPES:
        raise DiagnosisValidationError(f"unknown incident_type: {incident_type!r}")

    if recommended_action not in _SUPPORTED_RECOMMENDED_ACTIONS:
        raise DiagnosisValidationError(
            f"unsupported recommended_action: {recommended_action!r}"
        )

    if not (0.0 <= confidence <= 1.0):
        raise DiagnosisValidationError(f"confidence out of range: {confidence}")

    if not hypothesis:
        raise DiagnosisValidationError("hypothesis must not be empty")

    # Fail closed for weak evidence: a diagnosis with no limitations and low
    # confidence is treated as untrustworthy.
    human_review_required = bool(limitations) is False and confidence <= 0.60
    if confidence <= 0.49:
        human_review_required = True

    return StructuredDiagnosis(
        incident_type=incident_type,
        confidence=confidence,
        hypothesis=hypothesis,
        evidence_refs=evidence_refs,
        limitations=limitations,
        recommended_action=recommended_action,
        human_review_required=human_review_required,
        model=model,
        raw_model_id=raw_model_id,
        evaluated_at=evaluated_at,
    )


# ---------------------------------------------------------------------------
# Lightweight fake model for deterministic evals / demo
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FixtureModelClient:
    """Deterministic model client that returns a fixture payload.

    Used by benchmarks and demo so results are reproducible and the LLM path
    can be exercised without a real provider.
    """

    payload: dict[str, Any]
    model: str = "fixture-v1"
    raw_model_id: str | None = None

    def complete(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        del payload  # no-op: fixture ignores the prompt and returns its payload
        return dict(self.payload)

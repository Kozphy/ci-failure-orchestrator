"""Provisional SLO definitions and evaluator for foundation observability."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from .sli import SLIResult


class SLOStatus(str, Enum):
    MET = "MET"
    MISSED = "MISSED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class SLODefinition:
    slo_id: str
    sli_id: str
    target: float
    comparison: str = ">="  # >= or <=
    window: str = "retained_local_runs"
    minimum_samples: int = 1
    provisional: bool = True
    rationale: str = ""
    required: bool = True
    supports_error_budget: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "slo_id": self.slo_id,
            "sli_id": self.sli_id,
            "target": self.target,
            "comparison": self.comparison,
            "window": self.window,
            "minimum_samples": self.minimum_samples,
            "provisional": self.provisional,
            "rationale": self.rationale,
            "required": self.required,
            "supports_error_budget": self.supports_error_budget,
            "target_kind": "EXAMPLE_TARGET",
        }


@dataclass
class ErrorBudget:
    allowed_bad_events: float
    observed_bad_events: float
    remaining_budget: float

    def to_dict(self) -> dict[str, float]:
        return {
            "allowed_bad_events": self.allowed_bad_events,
            "observed_bad_events": self.observed_bad_events,
            "remaining_budget": self.remaining_budget,
        }


@dataclass
class SLOResult:
    slo_id: str
    sli_id: str
    status: SLOStatus
    observed_value: float | None
    target: float
    numerator: int
    denominator: int
    provisional: bool
    error_budget: ErrorBudget | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slo_id": self.slo_id,
            "sli_id": self.sli_id,
            "status": self.status.value,
            "observed_value": self.observed_value,
            "target": self.target,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "provisional": self.provisional,
            "target_kind": "EXAMPLE_TARGET",
            "error_budget": self.error_budget.to_dict() if self.error_budget else None,
            "detail": self.detail,
        }


def default_slo_definitions() -> list[SLODefinition]:
    """Conservative EXAMPLE targets — not measured production SLOs."""

    return [
        SLODefinition(
            slo_id="SLO-001",
            sli_id="SLI-005",
            target=1.0,
            minimum_samples=1,
            rationale="EXAMPLE: bounded retry compliance should be perfect for valid runs",
        ),
        SLODefinition(
            slo_id="SLO-002",
            sli_id="SLI-008",
            target=0.99,
            minimum_samples=5,
            rationale="EXAMPLE: audit completeness provisional target 99%",
        ),
        SLODefinition(
            slo_id="SLO-003",
            sli_id="SLI-006",
            target=1.0,
            minimum_samples=1,
            rationale="EXAMPLE: policy execution coverage for technical PASS runs",
        ),
        SLODefinition(
            slo_id="SLO-004",
            sli_id="SLI-007",
            target=1.0,
            minimum_samples=1,
            rationale="EXAMPLE: security block enforcement after detection",
        ),
        SLODefinition(
            slo_id="SLO-005",
            sli_id="SLI-009",
            target=0.99,
            minimum_samples=5,
            rationale="EXAMPLE: critical persistence success provisional 99%",
        ),
    ]


def load_slo_config(path: Path | None) -> list[SLODefinition]:
    if path is None or not Path(path).is_file():
        return default_slo_definitions()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("slos") if isinstance(data, dict) else data
    out: list[SLODefinition] = []
    for item in items or []:
        out.append(
            SLODefinition(
                slo_id=str(item["id"] if "id" in item else item["slo_id"]),
                sli_id=str(item.get("sli") or item["sli_id"]),
                target=float(item["target"]),
                comparison=str(item.get("comparison") or ">="),
                window=str(item.get("window") or "retained_local_runs"),
                minimum_samples=int(item.get("minimum_samples") or 1),
                provisional=bool(item.get("provisional", True)),
                rationale=str(item.get("rationale") or ""),
                required=bool(item.get("required", True)),
                supports_error_budget=bool(item.get("supports_error_budget", True)),
            )
        )
    return out


def evaluate_error_budget(
    *,
    target: float,
    numerator: int,
    denominator: int,
) -> ErrorBudget | None:
    """For >= ratio SLOs: allowed_bad = (1-target)*den; observed_bad = den-num."""

    if denominator <= 0 or target < 0 or target > 1:
        return None
    allowed = (1.0 - target) * float(denominator)
    observed_bad = float(max(0, denominator - numerator))
    remaining = allowed - observed_bad
    return ErrorBudget(
        allowed_bad_events=allowed,
        observed_bad_events=observed_bad,
        remaining_budget=remaining,
    )


def evaluate_slo(slo: SLODefinition, sli: SLIResult) -> SLOResult:
    if sli.denominator < slo.minimum_samples or sli.insufficient_data or sli.value is None:
        return SLOResult(
            slo_id=slo.slo_id,
            sli_id=slo.sli_id,
            status=SLOStatus.INSUFFICIENT_DATA,
            observed_value=sli.value,
            target=slo.target,
            numerator=sli.numerator,
            denominator=sli.denominator,
            provisional=slo.provisional,
            detail="insufficient samples or undefined ratio",
        )

    observed = sli.value
    if slo.comparison == ">=":
        met = observed >= slo.target
    elif slo.comparison == "<=":
        met = observed <= slo.target
    else:
        return SLOResult(
            slo_id=slo.slo_id,
            sli_id=slo.sli_id,
            status=SLOStatus.INSUFFICIENT_DATA,
            observed_value=observed,
            target=slo.target,
            numerator=sli.numerator,
            denominator=sli.denominator,
            provisional=slo.provisional,
            detail=f"unsupported comparison {slo.comparison}",
        )

    budget = None
    if slo.supports_error_budget and slo.comparison == ">=":
        budget = evaluate_error_budget(
            target=slo.target,
            numerator=sli.numerator,
            denominator=sli.denominator,
        )

    return SLOResult(
        slo_id=slo.slo_id,
        sli_id=slo.sli_id,
        status=SLOStatus.MET if met else SLOStatus.MISSED,
        observed_value=observed,
        target=slo.target,
        numerator=sli.numerator,
        denominator=sli.denominator,
        provisional=slo.provisional,
        error_budget=budget,
    )


def evaluate_slos(
    definitions: Sequence[SLODefinition],
    sli_results: Sequence[SLIResult],
) -> list[SLOResult]:
    by_id = {s.sli_id: s for s in sli_results}
    out: list[SLOResult] = []
    for slo in definitions:
        sli = by_id.get(slo.sli_id)
        if sli is None:
            out.append(
                SLOResult(
                    slo_id=slo.slo_id,
                    sli_id=slo.sli_id,
                    status=SLOStatus.INSUFFICIENT_DATA,
                    observed_value=None,
                    target=slo.target,
                    numerator=0,
                    denominator=0,
                    provisional=slo.provisional,
                    detail="SLI result missing",
                )
            )
            continue
        out.append(evaluate_slo(slo, sli))
    return out

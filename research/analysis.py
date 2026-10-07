"""Error analysis: assign every incorrect outcome to one class of ``taxonomy.ERROR_TAXONOMY``.

Assignment rules are deterministic and documented here so a reader can audit them:

Diagnosis (one entry per wrong prediction; NOT_RUN predictions are not errors):
* invalid or failed model output                      -> unknown (detail: invalid_output / provider_error)
* predicted class ``other`` for a non-``other`` case  -> insufficient_evidence
* wrong class                                          -> wrong_failure_class
* B2 wrong where B1 was right on the same case         -> context_selection_failure (instead of the above)
* wrong root stage on a multi-failure case             -> dependency_reasoning_failure for graph systems
                                                          (B3, B4), otherwise wrong_root_cause
* any wrong outcome on a flaky case                    -> also counted under flaky_or_nondeterministic

Repair (one entry per system decision that is not a correct acceptance, when it is an error):
* accepted fake fix               -> unsafe_repair; plus policy_false_negative for systems with a policy gate
* accepted semantically wrong     -> verification_gap
* accepted regression             -> regression_introduced
* correct candidate rejected by the policy gate          -> policy_false_positive
* correct candidate rejected or escalated by verification -> unknown (detail: verification_false_rejection)
* no green candidate although a correct one existed beyond the retry budget
                                  -> repair_did_not_fix_original_failure
* harness or product error        -> environment_mismatch
Escalating an incorrect candidate to a human is a safe outcome and is not an error.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .diagnosis import DiagnosisPrediction
from .repair import ACCEPTED, ERROR, ESCALATED, NO_GREEN, REJECTED, CandidateFacts, CaseRun, SystemDecision
from .taxonomy import ERROR_MITIGATIONS, ERROR_TAXONOMY

GRAPH_SYSTEMS = frozenset({"B3", "B4"})
POLICY_SYSTEMS = frozenset({"P", "P-composed", "P-no-verification", "P-no-retry"})


@dataclass(frozen=True)
class ErrorRecord:
    """One classified error."""

    track: str
    system: str
    case_id: str
    error_class: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return asdict(self)


def _diagnosis_classes(pred: DiagnosisPrediction, b1: DiagnosisPrediction | None) -> list[tuple[str, str]]:
    wrong_class = pred.class_correct is False
    wrong_root = pred.multi_failure and pred.root_correct is False
    if pred.status == "not_run" or not (wrong_class or wrong_root):
        return []
    out: list[tuple[str, str]] = []
    if pred.status in {"invalid", "error"}:
        out.append(("unknown", "invalid_output" if pred.status == "invalid" else "provider_error"))
    else:
        if wrong_class:
            if pred.system == "B2" and b1 is not None and b1.class_correct:
                out.append(("context_selection_failure", f"B1 correct, B2 predicted {pred.predicted_failure_class}"))
            elif pred.predicted_failure_class == "other" and pred.truth_class != "other":
                out.append(("insufficient_evidence", f"predicted other; truth {pred.truth_class}"))
            else:
                out.append(("wrong_failure_class", f"{pred.truth_class} -> {pred.predicted_failure_class}"))
        if wrong_root:
            cls = "dependency_reasoning_failure" if pred.system in GRAPH_SYSTEMS else "wrong_root_cause"
            out.append((cls, f"{pred.truth_root_stage} -> {pred.predicted_root_cause}"))
    if pred.truth_class == "flaky_or_nondeterministic":
        out.append(("flaky_or_nondeterministic", "wrong outcome on a flaky case"))
    return out


def diagnosis_errors(predictions: Sequence[DiagnosisPrediction]) -> list[ErrorRecord]:
    """Classify wrong diagnosis predictions."""
    b1_by_case = {p.case_id: p for p in predictions if p.system == "B1"}
    return [
        ErrorRecord("diagnosis", pred.system, pred.case_id, cls, detail)
        for pred in predictions
        for cls, detail in _diagnosis_classes(pred, b1_by_case.get(pred.case_id))
    ]


def _repair_classes(d: SystemDecision, fact: CandidateFacts | None, run: CaseRun, budget: int) -> list[tuple[str, str]]:
    cid = d.candidate_id or ""
    if d.decision == ERROR:
        return [("environment_mismatch", d.reason)]
    if d.decision == ACCEPTED and not d.correct:
        if d.label == "fake_fix":
            out = [("unsafe_repair", f"{cid} ({fact.fake_fix_kind if fact else '?'})")]
            if d.system in POLICY_SYSTEMS:
                out.append(("policy_false_negative", cid))
            return out
        if d.label == "semantically_wrong":
            return [("verification_gap", cid)]
        if d.label == "regression":
            return [("regression_introduced", cid)]
        return [("unknown", f"accepted incorrect {d.label} candidate {cid}")]
    if d.decision == REJECTED and d.correct:
        if d.reason == "policy_rejected":
            return [("policy_false_positive", cid)]
        return [("unknown", f"verification_false_rejection:{d.reason}")]
    if d.decision == ESCALATED and d.correct and d.reason.startswith("verification"):
        return [("unknown", f"verification_false_rejection:{d.reason}")]
    if d.decision == NO_GREEN and any(f.correct for f in run.facts[budget:]):
        return [("repair_did_not_fix_original_failure", "correct candidate only beyond the retry budget")]
    return []


def repair_errors(runs: Sequence[CaseRun], *, budget: int) -> list[ErrorRecord]:
    """Classify repair-track errors."""
    records: list[ErrorRecord] = []
    for run in runs:
        facts = {f.candidate_id: f for f in run.facts}
        for d in run.decisions:
            fact = facts.get(d.candidate_id) if d.candidate_id else None
            records += [
                ErrorRecord("repair", d.system, d.case_id, cls, detail)
                for cls, detail in _repair_classes(d, fact, run, budget)
            ]
    return records


def taxonomy_table(records: Sequence[ErrorRecord], total_outcomes: int) -> list[dict[str, Any]]:
    """One row per taxonomy class: count, share of all scored outcomes, systems, examples, mitigation."""
    grouped: dict[str, list[ErrorRecord]] = defaultdict(list)
    for record in records:
        grouped[record.error_class].append(record)
    rows = []
    for cls in ERROR_TAXONOMY:
        items = grouped.get(cls, [])
        rows.append({
            "error_class": cls,
            "count": len(items),
            "percent_of_outcomes": (100.0 * len(items) / total_outcomes) if total_outcomes else None,
            "systems": sorted({r.system for r in items}),
            "representative_case_ids": sorted({r.case_id for r in items})[:3],
            "mitigation": ERROR_MITIGATIONS[cls],
        })
    return rows

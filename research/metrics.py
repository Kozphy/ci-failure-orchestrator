"""Diagnosis and repair metrics. Unavailable values are ``None`` with a reason, never 0.

Definitions are documented in ``research/METRICS.md``; this module is the executable form.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .diagnosis import DiagnosisPrediction
from .repair import ACCEPTED, ESCALATED, NO_GREEN, REJECTED, CandidateFacts, CaseRun, SystemDecision
from .stats import bootstrap, mean_of, wilson


def unavailable(reason: str) -> dict[str, Any]:
    """Marker for a metric that could not be computed."""
    return {"value": None, "reason": reason}


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def classification_report(pairs: Sequence[tuple[str, str | None]]) -> dict[str, Any]:
    """Accuracy, macro P/R/F1, per-class scores and a confusion matrix over (truth, prediction) pairs.

    A ``None`` prediction (invalid or failed output) counts as wrong and appears as ``<none>``.
    Macro averages are over every class present in the truth or the predictions.
    """
    if not pairs:
        return {"n": 0, "accuracy": None, "macro_precision": None, "macro_recall": None, "macro_f1": None,
                "per_class": {}, "confusion": {}, "reason": "no scored cases"}
    labels = sorted({t for t, _ in pairs} | {p or "<none>" for _, p in pairs})
    confusion: dict[str, dict[str, int]] = {t: {} for t in sorted({t for t, _ in pairs})}
    for truth, pred in pairs:
        key = pred or "<none>"
        confusion[truth][key] = confusion[truth].get(key, 0) + 1
    per_class: dict[str, dict[str, Any]] = {}
    for label in labels:
        if label == "<none>":
            continue
        tp = sum(1 for t, p in pairs if t == label and p == label)
        fp = sum(1 for t, p in pairs if t != label and p == label)
        fn = sum(1 for t, p in pairs if t == label and p != label)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall else (
            0.0 if precision is not None and recall is not None else None
        )
        per_class[label] = {"support": tp + fn, "predicted": tp + fp, "precision": precision, "recall": recall,
                            "f1": f1}
    def macro(key: str) -> float | None:
        values = [v[key] if v[key] is not None else 0.0 for v in per_class.values()]
        return sum(values) / len(values) if values else None

    return {
        "n": len(pairs),
        "accuracy": sum(1 for t, p in pairs if t == p) / len(pairs),
        "macro_precision": macro("precision"),
        "macro_recall": macro("recall"),
        "macro_f1": macro("f1"),
        "macro_note": "undefined per-class precision/recall count as 0 in macro averages",
        "per_class": per_class,
        "confusion": confusion,
    }


def _macro_f1(pairs: Sequence[tuple[str, str | None]]) -> float | None:
    return classification_report(pairs)["macro_f1"]


def _accuracy(pairs: Sequence[tuple[str, str | None]]) -> float | None:
    return sum(1 for t, p in pairs if t == p) / len(pairs) if pairs else None


def diagnosis_metrics(
    predictions: Sequence[DiagnosisPrediction], *, seed: int, resamples: int
) -> dict[str, dict[str, Any]]:
    """Per-system diagnosis metrics with bootstrap CIs."""
    by_system: dict[str, list[DiagnosisPrediction]] = defaultdict(list)
    for pred in predictions:
        by_system[pred.system].append(pred)
    out: dict[str, dict[str, Any]] = {}
    for system, preds in by_system.items():
        not_run = [p for p in preds if p.status == "not_run"]
        scored = [p for p in preds if p.status != "not_run"]
        statuses = Counter(p.status for p in preds)
        base = {
            "n_cases": len(preds),
            "n_scored": len(scored),
            "n_not_run": len(not_run),
            "status_counts": dict(statuses),
            "claim_eligible": all(p.claim_eligible for p in scored) if scored else False,
        }
        if not scored:
            reason = not_run[0].reason if not_run else "no predictions"
            out[system] = {**base, "status": "NOT_RUN", "reason": reason,
                           "accuracy": unavailable(reason), "macro_f1": unavailable(reason)}
            continue
        pairs = [(p.truth_class, p.predicted_failure_class if p.status == "ok" else None) for p in scored]
        report = classification_report(pairs)
        multi = [p for p in scored if p.multi_failure and p.truth_root_stage]
        roots = [bool(p.root_correct) for p in multi]
        latencies = [p.latency_ms for p in scored if p.latency_ms is not None]
        tokens_in = [p.input_tokens for p in scored if p.input_tokens is not None]
        tokens_out = [p.output_tokens for p in scored if p.output_tokens is not None]
        costs = [p.cost_usd for p in scored if p.cost_usd is not None]
        out[system] = {
            **base,
            "status": "RUN",
            **report,
            "accuracy_ci": bootstrap(pairs, _accuracy, seed=seed, resamples=resamples),
            "macro_f1_ci": bootstrap(pairs, _macro_f1, seed=seed, resamples=resamples),
            "root_stage_accuracy_multi_failure": wilson(sum(roots), len(roots)),
            "latency_ms_p50": _quantile(latencies, 0.5) if latencies else unavailable("latency not recorded"),
            "latency_ms_p95": _quantile(latencies, 0.95) if latencies else unavailable("latency not recorded"),
            "input_tokens_total": sum(tokens_in) if tokens_in else unavailable("provider did not report tokens"),
            "output_tokens_total": sum(tokens_out) if tokens_out else unavailable("provider did not report tokens"),
            "cost_usd_total": sum(costs) if costs else unavailable("provider did not report cost"),
        }
    return out


def _correct_within(facts: Sequence[CandidateFacts], budget: int) -> bool:
    return any(f.correct for f in facts[:budget])


def repair_metrics(
    runs: Sequence[CaseRun], *, budget: int, seed: int, resamples: int
) -> dict[str, dict[str, Any]]:
    """Per-system case-level repair metrics with Wilson intervals and bootstrap CIs."""
    facts_by_case = {run.case_id: {f.candidate_id: f for f in run.facts} for run in runs}
    ordered_by_case = {run.case_id: run.facts for run in runs}
    by_system: dict[str, list[SystemDecision]] = defaultdict(list)
    for run in runs:
        for decision in run.decisions:
            by_system[decision.system].append(decision)
    out: dict[str, dict[str, Any]] = {}
    for system, decisions in by_system.items():
        n = len(decisions)
        system_budget = 1 if system in {"R-GREEN-1", "P-no-retry"} else budget

        def fact(d: SystemDecision) -> CandidateFacts | None:
            return facts_by_case[d.case_id].get(d.candidate_id) if d.candidate_id else None

        accepted = [d for d in decisions if d.decision == ACCEPTED]
        incorrect = [d for d in accepted if not d.correct]
        verified = [d for d in accepted if d.correct and (f := fact(d)) is not None and f.locally_verified]
        unverified = [d for d in accepted if (f := fact(d)) is not None and not f.locally_verified]
        unsafe = [d for d in accepted if d.label == "fake_fix"]
        regressions = [d for d in accepted if d.label == "regression"]
        green = [d for d in decisions if d.decision != NO_GREEN and d.candidate_id]
        missed = [
            d for d in decisions
            if _correct_within(ordered_by_case[d.case_id], system_budget) and not (d.decision == ACCEPTED and d.correct)
        ]
        def rate(items: Sequence[SystemDecision], n: int = n) -> dict[str, Any]:
            return wilson(len(items), n)

        per_case_incorrect = [1.0 if d.incorrect_acceptance else 0.0 for d in decisions]
        per_case_verified = [1.0 if d in verified else 0.0 for d in decisions]
        out[system] = {
            "n_cases": n,
            "retry_budget": system_budget,
            "repair_attempt_rate": rate([d for d in decisions if d.attempts > 0]),
            "ci_green_rate": rate(green),
            "acceptance_rate": rate(accepted),
            "verified_repair_rate": rate(verified),
            "green_but_unverified_rate": rate(unverified),
            "green_but_wrong_rate": rate(incorrect),
            "regression_rate": rate(regressions),
            "unsafe_remediation_rate": rate(unsafe),
            "policy_rejection_rate": rate([d for d in decisions if d.decision == REJECTED and d.reason == "policy_rejected"]),
            "verification_rejection_rate": rate(
                [d for d in decisions if d.decision == REJECTED and d.reason.startswith("verification")]
            ),
            "human_escalation_rate": rate([d for d in decisions if d.decision == ESCALATED]),
            "retry_budget_exhaustion_rate": rate([d for d in decisions if d.retry_budget_exhausted]),
            "missed_correct_repair_rate": rate(missed),
            "mean_attempts": mean_of([float(d.attempts) for d in decisions]),
            "green_but_wrong_rate_bootstrap": bootstrap(per_case_incorrect, mean_of, seed=seed, resamples=resamples),
            "verified_repair_rate_bootstrap": bootstrap(per_case_verified, mean_of, seed=seed, resamples=resamples),
            "cost_usd_total": unavailable("scripted candidates; no model calls on the repair track"),
            "tokens_total": unavailable("scripted candidates; no model calls on the repair track"),
        }
    return out


GATES: dict[str, str] = {
    "ci_green_only": "accept any candidate that turns visible CI green (R-GREEN rule)",
    "policy_only": "green and policy APPROVE (P without the verification layer)",
    "verification_only": "green and locally verified with policy removed (P without the policy gate)",
    "policy_and_verification": "green, policy APPROVE and locally verified (P's acceptance rule)",
}


def gate_accepts(gate: str, fact: CandidateFacts) -> bool:
    """Whether an acceptance rule would accept this candidate on its own (order-independent)."""
    if not fact.ci_green:
        return False
    if gate == "ci_green_only":
        return True
    if gate == "policy_only":
        return fact.policy_outcome == "APPROVE"
    if gate == "verification_only":
        return fact.verified_without_policy
    if gate == "policy_and_verification":
        return fact.policy_outcome == "APPROVE" and fact.locally_verified
    raise ValueError(f"unknown gate {gate!r}")


def candidate_gate_metrics(runs: Sequence[CaseRun]) -> dict[str, Any]:
    """Order-independent view: of the candidates that turn CI green, which does each gate accept, by label?"""
    facts = [f for run in runs for f in run.facts if f.error is None]
    green = [f for f in facts if f.ci_green]
    labels = sorted({f.label for f in facts})
    out: dict[str, Any] = {
        "n_candidates": len(facts),
        "n_green_candidates": len(green),
        "green_by_label": {lab: sum(1 for f in green if f.label == lab) for lab in labels},
        "candidates_by_label": {lab: sum(1 for f in facts if f.label == lab) for lab in labels},
        "green_incorrect": sum(1 for f in green if not f.correct),
        "gates": {},
    }
    for gate, description in GATES.items():
        accepted = [f for f in green if gate_accepts(gate, f)]
        incorrect_green = [f for f in green if not f.correct]
        correct_green = [f for f in green if f.correct]
        out["gates"][gate] = {
            "description": description,
            "accepted_incorrect": wilson(sum(1 for f in accepted if not f.correct), len(incorrect_green)),
            "rejected_correct": wilson(sum(1 for f in correct_green if not gate_accepts(gate, f)), len(correct_green)),
            "accepted_by_label": {
                lab: wilson(sum(1 for f in accepted if f.label == lab), sum(1 for f in green if f.label == lab))
                for lab in labels
            },
            "accepted_incorrect_ids": sorted(f"{f.case_id}/{f.candidate_id}" for f in accepted if not f.correct),
        }
    return out


def operational_metrics(runs: Sequence[CaseRun]) -> dict[str, Any]:
    """Harness latency (candidate evaluation through the product pipeline and oracle)."""
    candidate = [float(f.latency_ms) for run in runs for f in run.facts]
    case = [float(run.latency_ms) for run in runs]
    return {
        "candidate_latency_ms_p50": _quantile(candidate, 0.5),
        "candidate_latency_ms_p95": _quantile(candidate, 0.95),
        "case_latency_ms_p50": _quantile(case, 0.5),
        "case_latency_ms_p95": _quantile(case, 0.95),
        "note": "local Windows/Linux wall-clock for fixture repositories; not comparable to production CI latency",
    }


def fidelity_summary(runs: Sequence[CaseRun]) -> dict[str, Any]:
    """Agreement between the real product loop (P) and P's rules replayed over candidate facts."""
    checked = [run for run in runs if run.fidelity.get("checked")]
    disagreements = [
        {"case_id": run.case_id, "real": run.fidelity["real"], "composed": run.fidelity["composed"]}
        for run in checked if not run.fidelity["agree"]
    ]
    return {"checked": len(checked), "agree": len(checked) - len(disagreements), "disagreements": disagreements}


def annotation_summary(runs: Sequence[CaseRun]) -> dict[str, Any]:
    """Fixture QA issues observed during the run (must be empty for a valid repair evaluation)."""
    issues: list[str] = []
    for run in runs:
        issues += [f"{run.case_id}:{i}" for i in run.base_checks.get("issues", [])]
        for fact in run.facts:
            issues += [f"{run.case_id}/{fact.candidate_id}:{i}" for i in fact.annotation_issues]
            if fact.error:
                issues.append(f"{run.case_id}/{fact.candidate_id}:error:{fact.error}")
    return {"issues": issues, "count": len(issues)}


def ok_rate(values: Mapping[str, Any]) -> float | None:
    """Extract the point estimate from a Wilson record."""
    return values.get("estimate") if isinstance(values, Mapping) else None

"""Diagnosis track (RQ2): B0, B1, B2, B3, B4 on research cases.

* B0 - latest visible failure: the deepest failed stage; class from the product classifier on its log.
* B3 - dependency graph only: ``RootCauseRanker`` top stage; class from the classifier on that stage's log.
* B1 - model, logs only.  B2 - model, logs + bounded repository context (``ctx-v1``).
* B4 - model, logs + context + pipeline graph + the B3 ranking.

P's diagnosis path is the product classifier plus the dependency ranker, i.e. exactly B3; memory is not
used in this evaluation. P-diagnosis is therefore reported as identical to B3 by construction rather
than as a separate result.

Classifier confidences are heuristic and uncalibrated; they are reported only as ordinal levels.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from string import Template
from typing import Any

from ci_failure_orchestrator.corpus_benchmark import build_graph, failures_for_case
from ci_failure_orchestrator.foundation.classifier import FailureClassifier
from ci_failure_orchestrator.foundation.models import FailureEvent
from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.ranker import RootCauseRanker

from .paths import PROMPTS_DIR
from .providers import NOT_RUN, OK, LLMRequest, Provider, parse_prediction
from .taxonomy import CONFIDENCE_LEVELS, FAILURE_CATEGORIES, RECOMMENDED_ACTIONS, to_research_category

CONTEXT_POLICY = "ctx-v1"
CTX_MAX_CHANGED_PATHS = 20
CTX_MAX_FILES = 4
CTX_MAX_FILE_CHARS = 1200
CTX_MAX_WORKFLOW_CHARS = 1200
CTX_MAX_TOTAL_CHARS = 6000
MAX_LOG_CHARS = 2000

DETERMINISTIC_SYSTEMS = ("B0", "B3")
MODEL_SYSTEMS = {"B1": "b1_log_only.v1", "B2": "b2_context.v1", "B4": "b4_graph_context.v1"}
DIAGNOSIS_SYSTEMS = ("B0", "B1", "B2", "B3", "B4")

CATEGORY_ACTIONS: dict[str, str] = {
    "dependency": "repair_dependency",
    "compilation_or_syntax": "repair_code",
    "lint_or_formatting": "repair_code",
    "unit_test": "repair_code",
    "integration_test": "repair_code",
    "configuration": "repair_configuration",
    "security_or_policy": "block_and_escalate",
    "flaky_or_nondeterministic": "retry_or_quarantine",
    "timeout_or_resource": "investigate_infrastructure",
    "infrastructure_or_environment": "investigate_infrastructure",
    "cross_job_dependency": "repair_configuration",
    "other": "escalate_to_human",
}


def ordinal_confidence(value: float) -> str:
    """Bucket a heuristic score into an ordinal level (not a calibrated probability)."""
    if value < 0.6:
        return CONFIDENCE_LEVELS[0]
    if value < 0.8:
        return CONFIDENCE_LEVELS[1]
    return CONFIDENCE_LEVELS[2]


@dataclass(frozen=True)
class DiagnosisPrediction:
    """One system's diagnosis of one case, scored against the ground truth."""

    system: str
    case_id: str
    status: str
    predicted_failure_class: str | None
    predicted_root_cause: str | None
    confidence: str | None
    evidence: list[str]
    recommended_action: str | None
    truth_class: str
    truth_root_stage: str | None
    class_correct: bool | None
    root_correct: bool | None
    multi_failure: bool
    reason: str
    claim_eligible: bool
    request_digest: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return asdict(self)


def case_stages(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The pipeline stages of a case; cases without a pipeline get independent observed stages."""
    pipeline = case.get("pipeline") or {}
    if pipeline.get("stages"):
        return [
            {"id": s["id"], "depends_on": list(s.get("depends_on", [])), "criticality": float(s.get("criticality", 0.5))}
            for s in pipeline["stages"]
        ]
    seen: list[str] = []
    for failure in case["observed_failures"]:
        if failure["stage"] not in seen:
            seen.append(failure["stage"])
    return [{"id": stage, "depends_on": [], "criticality": 0.5} for stage in seen]


def _ordered_failures(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    indexed = list(enumerate(case["observed_failures"]))
    return [f for _, f in sorted(indexed, key=lambda item: (item[1].get("order", item[0]), item[0]))]


def _corpus(case: Mapping[str, Any]) -> tuple[PipelineGraph, list[Any]]:
    corpus_case = {
        "failures": [
            {k: v for k, v in {
                "stage": f["stage"], "error_type": f["error_type"], "message": f.get("log_excerpt") or "",
                "severity": f.get("severity"), "confidence": f.get("confidence"),
            }.items() if v is not None}
            for f in _ordered_failures(case)
        ]
    }
    return build_graph({"stages": case_stages(case)}), failures_for_case(corpus_case)


def _classify(case: Mapping[str, Any], failure: Mapping[str, Any]) -> tuple[str, float, list[str]]:
    stage = str(failure["stage"])
    on_failed_job = stage == case.get("failed_job")
    event = FailureEvent.from_dict({
        "workflow": case.get("workflow") or "",
        "job": stage,
        "failed_step": (case.get("failed_step") or stage) if on_failed_job else stage,
        "message": "",
        "log_excerpt": str(failure.get("log_excerpt") or "")[:MAX_LOG_CHARS],
        "changed_paths": list((case.get("failure_time_context") or {}).get("changed_paths") or []),
    }, run_id="research-diagnosis")
    result = FailureClassifier().classify(event)
    return to_research_category(result.category), float(result.confidence), list(result.evidence)


def _truth(case: Mapping[str, Any]) -> tuple[str, str | None, bool]:
    return (
        str(case["failure_category"]),
        case["ground_truth"].get("root_cause_stage"),
        len({f["stage"] for f in case["observed_failures"]}) > 1,
    )


def _deterministic(system: str, case: Mapping[str, Any]) -> DiagnosisPrediction:
    started = time.perf_counter()
    graph, failures = _corpus(case)
    if system == "B0":
        top = max(failures, key=lambda f: graph.depth(f.stage)).stage
        reason = "deepest failed stage"
    else:
        ranked = RootCauseRanker(graph).rank(failures)
        top = ranked[0].failure.stage
        reason = f"ranker score={ranked[0].score}"
    source = next(f for f in _ordered_failures(case) if f["stage"] == top)
    category, score, evidence = _classify(case, source)
    truth_class, truth_root, multi = _truth(case)
    return DiagnosisPrediction(
        system=system, case_id=case["case_id"], status=OK, predicted_failure_class=category,
        predicted_root_cause=top, confidence=ordinal_confidence(score), evidence=evidence,
        recommended_action=CATEGORY_ACTIONS[category], truth_class=truth_class, truth_root_stage=truth_root,
        class_correct=category == truth_class, root_correct=(top == truth_root) if truth_root else None,
        multi_failure=multi, reason=reason, claim_eligible=True,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def render_failures(case: Mapping[str, Any]) -> str:
    """Observed failures as prompt text (stage and log only; no labels)."""
    blocks = []
    for failure in _ordered_failures(case):
        log = str(failure.get("log_excerpt") or "(no log excerpt)")[:MAX_LOG_CHARS]
        blocks.append(f"stage: {failure['stage']}\nlog:\n{log}")
    return "\n\n".join(blocks)


def render_context(case: Mapping[str, Any]) -> str:
    """Bounded, deterministic repository context (policy ``ctx-v1``)."""
    ctx = case.get("failure_time_context") or {}
    parts: list[str] = []
    changed = sorted(ctx.get("changed_paths") or [])[:CTX_MAX_CHANGED_PATHS]
    if changed:
        parts.append("Changed paths:\n" + "\n".join(f"- {p}" for p in changed))
    if ctx.get("workflow_excerpt"):
        parts.append("Workflow excerpt:\n" + str(ctx["workflow_excerpt"])[:CTX_MAX_WORKFLOW_CHARS])
    for item in sorted(ctx.get("files") or [], key=lambda f: f["path"])[:CTX_MAX_FILES]:
        parts.append(f"File {item['path']}:\n{item['excerpt'][:CTX_MAX_FILE_CHARS]}")
    text = "\n\n".join(parts) if parts else "(no repository context was captured for this case)"
    return text[:CTX_MAX_TOTAL_CHARS]


def render_graph(case: Mapping[str, Any]) -> str:
    """Pipeline graph as ``stage <- deps`` lines."""
    return "\n".join(
        f"{s['id']} <- {', '.join(s['depends_on']) if s['depends_on'] else '(none)'}" for s in case_stages(case)
    )


def render_ranking(case: Mapping[str, Any]) -> str:
    """The B3 ranking as prompt text."""
    graph, failures = _corpus(case)
    ranked = RootCauseRanker(graph).rank(failures)
    return "\n".join(f"{idx}. {r.failure.stage} score={r.score}" for idx, r in enumerate(ranked, start=1))


def load_prompt(prompt_id: str, prompts_dir: Path = PROMPTS_DIR) -> tuple[str, str]:
    """Return the prompt template text and its SHA-256 (prompts are versioned by file name)."""
    text = (prompts_dir / f"{prompt_id}.txt").read_bytes().decode("utf-8")
    return text, sha256(text.encode("utf-8")).hexdigest()


def build_prompt(system: str, case: Mapping[str, Any], prompts_dir: Path = PROMPTS_DIR) -> LLMRequest:
    """Render the versioned prompt for a model system and case."""
    prompt_id = MODEL_SYSTEMS[system]
    template, digest = load_prompt(prompt_id, prompts_dir)
    values = {
        "categories": ", ".join(FAILURE_CATEGORIES),
        "confidence_levels": ", ".join(CONFIDENCE_LEVELS),
        "actions": ", ".join(RECOMMENDED_ACTIONS),
        "workflow": case.get("workflow") or "(unknown)",
        "failed_job": case.get("failed_job") or "(unknown)",
        "failed_step": case.get("failed_step") or "(unknown)",
        "failures": render_failures(case),
        "context_policy": CONTEXT_POLICY,
        "context": render_context(case),
        "graph": render_graph(case),
        "ranking": render_ranking(case),
    }
    prompt = Template(template).substitute(values)
    return LLMRequest(system=system, case_id=case["case_id"], prompt_id=prompt_id, prompt_sha256=digest, prompt=prompt)


def _model(system: str, case: Mapping[str, Any], provider: Provider, prompts_dir: Path) -> DiagnosisPrediction:
    request = build_prompt(system, case, prompts_dir)
    response = provider.complete(request)
    truth_class, truth_root, multi = _truth(case)
    common = {
        "system": system, "case_id": case["case_id"], "truth_class": truth_class, "truth_root_stage": truth_root,
        "multi_failure": multi, "claim_eligible": provider.claim_eligible, "request_digest": request.digest,
        "latency_ms": response.latency_ms, "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens, "cost_usd": response.cost_usd,
    }
    if response.status == NOT_RUN:
        return DiagnosisPrediction(
            **common, status=NOT_RUN, predicted_failure_class=None, predicted_root_cause=None, confidence=None,
            evidence=[], recommended_action=None, class_correct=None, root_correct=None, reason=response.reason,
        )
    if response.status != OK:
        return DiagnosisPrediction(
            **common, status="error", predicted_failure_class=None, predicted_root_cause=None, confidence=None,
            evidence=[], recommended_action=None, class_correct=False, root_correct=False if truth_root else None,
            reason=response.reason,
        )
    parsed = parse_prediction(response.text, [s["id"] for s in case_stages(case)])
    status = OK if not parsed.errors else "invalid"
    return DiagnosisPrediction(
        **common, status=status, predicted_failure_class=parsed.predicted_failure_class,
        predicted_root_cause=parsed.predicted_root_cause, confidence=parsed.confidence, evidence=parsed.evidence,
        recommended_action=parsed.recommended_action,
        class_correct=parsed.predicted_failure_class == truth_class and not parsed.errors,
        root_correct=(parsed.predicted_root_cause == truth_root and not parsed.errors) if truth_root else None,
        reason=response.reason, validation_errors=parsed.errors,
    )


def diagnose(
    system: str, case: Mapping[str, Any], provider: Provider, prompts_dir: Path = PROMPTS_DIR
) -> DiagnosisPrediction:
    """Run one diagnosis system on one case."""
    if system in DETERMINISTIC_SYSTEMS:
        return _deterministic(system, case)
    if system in MODEL_SYSTEMS:
        return _model(system, case, provider, prompts_dir)
    raise ValueError(f"unknown diagnosis system {system!r}")


def run_diagnosis(
    cases: Sequence[Mapping[str, Any]], systems: Sequence[str], provider: Provider, prompts_dir: Path = PROMPTS_DIR
) -> list[DiagnosisPrediction]:
    """Run every requested system on every diagnosis-track case, in case order."""
    return [
        diagnose(system, case, provider, prompts_dir)
        for case in cases if "diagnosis" in case.get("tracks", ["diagnosis"])
        for system in systems
    ]

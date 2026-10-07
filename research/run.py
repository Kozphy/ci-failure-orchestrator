"""Run a research experiment: ``python -m research.run --config research/config/default.yaml``.

Outputs go to ``<raw_dir>/<experiment_id>/`` and are written with exclusive-create semantics, so an
existing raw result is never overwritten. Processed tables are regenerated from raw results by
``research.report`` and may be overwritten.

Holdout cases are refused unless the config sets ``dataset.allow_holdout: true`` *and* the command line
passes ``--confirm-holdout``; every holdout evaluation is appended to ``results/holdout_ledger.jsonl``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .analysis import diagnosis_errors, repair_errors, taxonomy_table
from .dataset import load_dataset, read_lock, validate_dataset
from .diagnosis import CONTEXT_POLICY, DIAGNOSIS_SYSTEMS, MODEL_SYSTEMS, DiagnosisPrediction, load_prompt, run_diagnosis
from .manifest import build_manifest, config_digest, contains_secret_shape, git_state, utc_timestamp
from .metrics import (
    annotation_summary,
    candidate_gate_metrics,
    diagnosis_metrics,
    fidelity_summary,
    operational_metrics,
    repair_metrics,
)
from .paths import HOLDOUT_LEDGER_PATH, PROCESSED_DIR, RAW_DIR, ROOT, SPLIT_ALIASES, SPLITS
from .providers import build_provider
from .repair import SYSTEMS_DOC, CaseRun, run_case
from .report import write_processed
from .stats import mcnemar_exact, paired_bootstrap

SYSTEM_VERSIONS: dict[str, str] = {
    "B0": "b0-latest-visible/v1 (ci_failure_orchestrator.baselines rule on research cases)",
    "B1": "b1-llm-log-only/v1 (prompt b1_log_only.v1)",
    "B2": "b2-llm-context/v1 (prompt b2_context.v1, context ctx-v1)",
    "B3": "b3-dependency-graph/v1 (RootCauseRanker + FailureClassifier)",
    "B4": "b4-graph-llm/v1 (prompt b4_graph_context.v1, context ctx-v1)",
    "R-GREEN-1": "r-green/v1 budget=1",
    "R-GREEN-k": "r-green/v1 budget=k",
    "P": "run_fix_repo at manifest git_commit",
    "P-composed": "p-composed/v1",
    "P-no-policy": "ablation/v1",
    "P-no-verification": "ablation/v1",
    "P-no-retry": "ablation/v1",
}
REPAIR_COMPARISONS = (
    ("P", "R-GREEN-k"), ("P", "R-GREEN-1"), ("P", "P-no-policy"), ("P", "P-no-verification"), ("P", "P-no-retry"),
)
DIAGNOSIS_COMPARISONS = (("B3", "B0"), ("B2", "B1"), ("B4", "B2"), ("B4", "B3"))
RAW_FILES = (
    "manifest.json", "predictions.jsonl", "repairs.jsonl", "evidence.jsonl", "metrics.json",
    "confidence_intervals.json", "errors.jsonl",
)


class ExperimentError(RuntimeError):
    """The experiment cannot run as configured."""


def load_config(path: Path) -> dict[str, Any]:
    """Load a YAML experiment config."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ExperimentError(f"{path} must contain a YAML mapping")
    return data


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def select_cases(config: Mapping[str, Any], *, confirm_holdout: bool) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Validate the frozen dataset and return (splits, cases, lock)."""
    ds_cfg = config.get("dataset") or {}
    root = _resolve(ds_cfg.get("root", "research/datasets"))
    lock_path = _resolve(ds_cfg.get("lock", root / "dataset.lock.json"))
    dataset = load_dataset(root)
    lock = read_lock(lock_path)
    report = validate_dataset(dataset, lock=lock, require_lock=True)
    if not report.ok:
        raise ExperimentError("dataset validation failed: " + "; ".join(report.errors[:10]))
    splits = [SPLIT_ALIASES.get(s, s) for s in ds_cfg.get("splits", ["test"])]
    unknown = sorted(set(splits) - set(SPLITS))
    if unknown:
        raise ExperimentError(f"unknown splits {unknown}")
    if "holdout" in splits and not (ds_cfg.get("allow_holdout") and confirm_holdout):
        raise ExperimentError(
            "holdout evaluation requires dataset.allow_holdout: true and --confirm-holdout; "
            "never evaluate holdout cases while tuning prompts or rules"
        )
    cases = dataset.cases(splits)
    wanted = ds_cfg.get("case_ids")
    if wanted:
        missing = sorted(set(wanted) - {c["case_id"] for c in cases})
        if missing:
            raise ExperimentError(f"case_ids not in the selected splits: {missing}")
        cases = [c for c in cases if c["case_id"] in set(wanted)]
    return splits, cases, lock or {}


def experiment_id_for(config: Mapping[str, Any], now: datetime) -> str:
    """``<name>-<UTC timestamp>-<config hash prefix>``."""
    name = str((config.get("experiment") or {}).get("name") or "experiment")
    return f"{name}-{now.strftime('%Y%m%dT%H%M%SZ')}-{config_digest(config)[:8]}"


def _paired(a: Sequence[bool], b: Sequence[bool], seed: int, resamples: int) -> dict[str, Any]:
    return {
        "mcnemar": mcnemar_exact(a, b),
        "paired_bootstrap": paired_bootstrap([float(x) for x in a], [float(y) for y in b], seed=seed,
                                             resamples=resamples),
        "rate_a": sum(a) / len(a) if a else None,
        "rate_b": sum(b) / len(b) if b else None,
    }


def repair_comparisons(runs: Sequence[CaseRun], seed: int, resamples: int, budget: int) -> dict[str, Any]:
    """Paired comparisons of incorrect acceptance and verified repair between systems."""
    del budget
    by_system: dict[str, dict[str, Any]] = {}
    facts = {run.case_id: {f.candidate_id: f for f in run.facts} for run in runs}
    for run in runs:
        for d in run.decisions:
            by_system.setdefault(d.system, {})[d.case_id] = d
    out: dict[str, Any] = {}
    for a, b in REPAIR_COMPARISONS:
        if a not in by_system or b not in by_system:
            continue
        ids = sorted(set(by_system[a]) & set(by_system[b]))

        def verified(d: Any) -> bool:
            f = facts[d.case_id].get(d.candidate_id) if d.candidate_id else None
            return d.decision == "accepted" and bool(d.correct) and f is not None and f.locally_verified

        out[f"{a} vs {b}"] = {
            "n_pairs": len(ids),
            "incorrect_acceptance": _paired(
                [by_system[a][i].incorrect_acceptance for i in ids], [by_system[b][i].incorrect_acceptance for i in ids],
                seed, resamples,
            ),
            "verified_repair": _paired(
                [verified(by_system[a][i]) for i in ids], [verified(by_system[b][i]) for i in ids], seed, resamples
            ),
        }
    return out


def diagnosis_comparisons(predictions: Sequence[DiagnosisPrediction], seed: int, resamples: int) -> dict[str, Any]:
    """Paired comparisons of class and root-stage correctness on cases both systems scored."""
    table: dict[str, dict[str, DiagnosisPrediction]] = {}
    for p in predictions:
        table.setdefault(p.system, {})[p.case_id] = p
    out: dict[str, Any] = {}
    for a, b in DIAGNOSIS_COMPARISONS:
        if a not in table or b not in table:
            continue
        both = sorted(i for i in set(table[a]) & set(table[b])
                      if table[a][i].status != "not_run" and table[b][i].status != "not_run")
        excluded = len(set(table[a]) | set(table[b])) - len(both)
        if not both:
            out[f"{a} vs {b}"] = {"n_pairs": 0, "excluded_not_run": excluded, "reason": "a system was not run"}
            continue
        multi = [i for i in both if table[a][i].multi_failure and table[a][i].truth_root_stage]
        out[f"{a} vs {b}"] = {
            "n_pairs": len(both),
            "excluded_not_run": excluded,
            "class_correct": _paired([bool(table[a][i].class_correct) for i in both],
                                     [bool(table[b][i].class_correct) for i in both], seed, resamples),
            "root_correct_multi_failure": _paired([bool(table[a][i].root_correct) for i in multi],
                                                  [bool(table[b][i].root_correct) for i in multi], seed, resamples)
            if multi else {"n_pairs": 0, "reason": "no multi-failure cases"},
        }
    return out


def _confidence_intervals(metrics: Mapping[str, Any], comparisons: Mapping[str, Any]) -> dict[str, Any]:
    diag = {
        system: {k: v for k, v in m.items() if k.endswith("_ci") or k == "root_stage_accuracy_multi_failure"}
        for system, m in (metrics.get("diagnosis") or {}).items()
    }
    rep = {
        system: {k: v for k, v in m.items() if k.endswith(("_rate", "_bootstrap"))}
        for system, m in (metrics.get("repair") or {}).items()
    }
    return {"diagnosis": diag, "repair": rep, "comparisons": comparisons,
            "note": "Wilson 95% intervals for rates; percentile bootstrap over cases; exact McNemar for pairs"}


def _write_exclusive(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _jsonl(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)


def run_experiment(
    config: Mapping[str, Any],
    *,
    config_path: str | None = None,
    raw_root: Path | None = None,
    confirm_holdout: bool = False,
    command: Sequence[str] = (),
    now: datetime | None = None,
    log: Any = None,
) -> Path:
    """Run the configured experiment and return the raw output directory."""
    log = log or (lambda msg: print(msg, file=sys.stderr, flush=True))
    now = now or datetime.now(timezone.utc)
    git_at_start = git_state()
    exp = config.get("experiment") or {}
    seed = int(exp.get("seed", 0))
    resamples = int(exp.get("bootstrap_resamples", 2000))
    splits, cases, lock = select_cases(config, confirm_holdout=confirm_holdout)
    if (config.get("repair") or {}).get("require_real_ci"):
        raise ExperimentError("require_real_ci is true but fixture repositories have no real CI to confirm repairs")

    experiment_id = experiment_id_for(config, now)
    raw_root = raw_root or _resolve((config.get("output") or {}).get("raw_dir", RAW_DIR))
    out_dir = raw_root / experiment_id
    out_dir.mkdir(parents=True, exist_ok=False)

    diag_cfg = config.get("diagnosis") or {}
    rep_cfg = config.get("repair") or {}
    model_cfg = dict(config.get("model") or {})
    provider = build_provider(model_cfg)

    diag_systems = list(diag_cfg.get("systems", DIAGNOSIS_SYSTEMS)) if diag_cfg.get("enabled", True) else []
    diag_cases = [c for c in cases if "diagnosis" in c.get("tracks", [])]
    log(f"[{experiment_id}] diagnosis: {len(diag_cases)} cases x {diag_systems}")
    predictions = run_diagnosis(diag_cases, diag_systems, provider) if diag_systems else []

    rep_systems = list(rep_cfg.get("systems", SYSTEMS_DOC)) if rep_cfg.get("enabled", True) else []
    rep_cases = [c for c in cases if "repair" in c.get("tracks", [])]
    budget = int(rep_cfg.get("retry_budget", 3))
    order_seed = int(rep_cfg.get("candidate_order_seed", seed))
    timeout = int(rep_cfg.get("timeout_seconds", 300))
    runs: list[CaseRun] = []
    for idx, case in enumerate(rep_cases if rep_systems else [], start=1):
        log(f"[{experiment_id}] repair {idx}/{len(rep_cases)}: {case['case_id']}")
        runs.append(run_case(case, seed=order_seed, budget=budget, timeout=timeout, systems=rep_systems))

    metrics: dict[str, Any] = {
        "experiment_id": experiment_id,
        "diagnosis": diagnosis_metrics(predictions, seed=seed, resamples=resamples),
        "repair": repair_metrics(runs, budget=budget, seed=seed, resamples=resamples) if runs else {},
        "candidate_gates": candidate_gate_metrics(runs) if runs else {},
        "operational": operational_metrics(runs) if runs else {},
        "fidelity": fidelity_summary(runs) if runs else {},
        "annotation": annotation_summary(runs) if runs else {"issues": [], "count": 0},
    }
    comparisons = {
        "diagnosis": diagnosis_comparisons(predictions, seed, resamples),
        "repair": repair_comparisons(runs, seed, resamples, budget) if runs else {},
    }
    metrics["comparisons"] = comparisons
    err_records = diagnosis_errors(predictions) + repair_errors(runs, budget=budget)
    total_outcomes = len([p for p in predictions if p.status != "not_run"]) + sum(len(r.decisions) for r in runs)
    metrics["error_taxonomy"] = taxonomy_table(err_records, total_outcomes)

    errors: list[dict[str, Any]] = [r.to_dict() | {"kind": "classified_error"} for r in err_records]
    errors += [{"kind": "not_run", "system": p.system, "case_id": p.case_id, "reason": p.reason}
               for p in predictions if p.status == "not_run"]
    errors += [{"kind": "invalid_model_output", "system": p.system, "case_id": p.case_id,
                "validation_errors": p.validation_errors} for p in predictions if p.status == "invalid"]
    errors += [{"kind": "annotation_issue", "detail": i} for i in metrics["annotation"]["issues"]]
    errors += [{"kind": "fidelity_disagreement", **d} for d in (metrics["fidelity"] or {}).get("disagreements", [])]

    prompts = {}
    for system in diag_systems:
        if system in MODEL_SYSTEMS:
            prompts[MODEL_SYSTEMS[system]] = load_prompt(MODEL_SYSTEMS[system])[1]
    manifest = build_manifest(
        experiment_id=experiment_id,
        timestamp=utc_timestamp(),
        config=config,
        config_path=config_path,
        lock=lock,
        splits=splits,
        case_ids={"diagnosis": [c["case_id"] for c in diag_cases] if diag_systems else [],
                  "repair": [c["case_id"] for c in rep_cases] if rep_systems else []},
        systems={"diagnosis": diag_systems, "repair": rep_systems},
        system_versions={s: SYSTEM_VERSIONS[s] for s in [*diag_systems, *rep_systems]},
        prompts=prompts,
        provider={**model_cfg, "provider": provider.name, "claim_eligible": provider.claim_eligible},
        command=command,
        extra={"context_policy": CONTEXT_POLICY,
               "exclusions": {"diagnosis_not_run": sum(p.status == "not_run" for p in predictions)}},
        git=git_at_start,
    )
    texts = {
        "manifest.json": json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        "predictions.jsonl": _jsonl([p.to_dict() for p in predictions]),
        "repairs.jsonl": _jsonl([d.to_dict() for run in runs for d in run.decisions]),
        "evidence.jsonl": _jsonl(
            [{"kind": "candidate", **f.to_dict()} for run in runs for f in run.facts]
            + [{"kind": "case", "case_id": r.case_id, "order": r.order, "base_checks": r.base_checks,
                "fidelity": r.fidelity, "latency_ms": r.latency_ms} for r in runs]
        ),
        "metrics.json": json.dumps(metrics, indent=2, sort_keys=True) + "\n",
        "confidence_intervals.json": json.dumps(_confidence_intervals(metrics, comparisons), indent=2,
                                                sort_keys=True) + "\n",
        "errors.jsonl": _jsonl(errors),
    }
    leaked = [name for name, text in texts.items() if contains_secret_shape(text)]
    if leaked:
        raise ExperimentError(f"refusing to write outputs containing credential-shaped strings: {leaked}")
    for name in RAW_FILES:
        _write_exclusive(out_dir / name, texts[name])
    if "holdout" in splits:
        HOLDOUT_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HOLDOUT_LEDGER_PATH.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"experiment_id": experiment_id, "timestamp": manifest["timestamp"],
                                     "git_commit": manifest["git_commit"], "config_sha256": manifest["config_sha256"],
                                     "case_ids": [c["case_id"] for c in cases if c["split"] == "holdout"]},
                                    sort_keys=True) + "\n")
    log(f"[{experiment_id}] wrote {out_dir}")
    return out_dir


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, help="override output.raw_dir")
    parser.add_argument("--processed-dir", type=Path, help="override output.processed_dir")
    parser.add_argument("--no-processed", action="store_true", help="do not regenerate processed tables")
    parser.add_argument("--confirm-holdout", action="store_true")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    try:
        out_dir = run_experiment(
            config, config_path=args.config.as_posix(), raw_root=args.raw_dir,
            confirm_holdout=args.confirm_holdout, command=["python", "-m", "research.run", *(argv or sys.argv[1:])],
        )
    except ExperimentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    output = config.get("output") or {}
    if not args.no_processed and output.get("update_processed", True):
        processed = args.processed_dir or _resolve(output.get("processed_dir", PROCESSED_DIR))
        write_processed(out_dir, processed)
        print(f"processed tables: {processed}")
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
